"""Vehicle-reference timeline aligned to dense post-run windows."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Literal

from vibesensor.domain import OrderReferenceSpec
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.shared.types.whole_run_analysis import WholeRunWindowDescriptor
from vibesensor.use_cases.diagnostics.post_run_stft import (
    PostRunDenseStftResult,
    PostRunStftFrame,
)

type VehicleReferenceValueQuality = Literal["sampled", "interpolated", "unavailable"]
type VehicleReferenceUnavailableReason = Literal[
    "missing_speed",
    "stale_speed",
    "missing_rpm",
    "missing_gear",
    "inconsistent_sample_rate",
    "unknown_final_drive",
    "unknown_tire",
    "ambiguous_gap",
    "no_samples",
]


@dataclass(frozen=True, slots=True)
class VehicleReferenceTimelineConfig:
    """Conservative alignment settings for vehicle-reference values."""

    max_interpolation_gap_s: float = 1.0
    max_stale_sample_age_s: float = 0.75


@dataclass(frozen=True, slots=True)
class VehicleReferencePoint:
    """Vehicle reference values aligned to one dense analysis window."""

    run_id: str
    window_index: int
    window_start_t_s: float
    window_end_t_s: float
    window_center_t_s: float
    speed_kmh: float | None
    speed_source: str | None
    speed_quality: VehicleReferenceValueQuality
    engine_rpm: float | None
    engine_rpm_source: str | None
    engine_rpm_quality: VehicleReferenceValueQuality
    gear_ratio: float | None
    gear_quality: VehicleReferenceValueQuality
    final_drive_ratio: float | None
    final_drive_quality: VehicleReferenceValueQuality
    wheel_hz: float | None
    driveshaft_hz: float | None
    engine_hz: float | None
    wheel_uncertainty_pct: float | None
    driveshaft_uncertainty_pct: float | None
    engine_uncertainty_pct: float | None
    unavailable_reasons: tuple[VehicleReferenceUnavailableReason, ...]


@dataclass(frozen=True, slots=True)
class VehicleReferenceTimeline:
    """Dense-window vehicle reference timeline."""

    run_id: str
    config: VehicleReferenceTimelineConfig
    points: tuple[VehicleReferencePoint, ...]

    def point_for_window(self, window_index: int) -> VehicleReferencePoint | None:
        for point in self.points:
            if point.window_index == window_index:
                return point
        return None


@dataclass(frozen=True, slots=True)
class VehicleReferenceDebugFixture:
    """Compact reusable fixture row for later order-tracking tests."""

    window_index: int
    t_s: float
    speed_kmh: float | None
    wheel_hz: float | None
    driveshaft_hz: float | None
    engine_hz: float | None
    unavailable_reasons: tuple[VehicleReferenceUnavailableReason, ...]


@dataclass(frozen=True, slots=True)
class _TimedValue:
    t_s: float
    value: float
    source: str | None


@dataclass(frozen=True, slots=True)
class _AlignedValue:
    value: float | None
    source: str | None
    quality: VehicleReferenceValueQuality
    reason: VehicleReferenceUnavailableReason | None = None


def build_post_run_vehicle_reference_timeline(
    *,
    run_id: str,
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
    windows: (
        PostRunDenseStftResult | Iterable[PostRunStftFrame] | Iterable[WholeRunWindowDescriptor]
    ),
    config: VehicleReferenceTimelineConfig | None = None,
) -> VehicleReferenceTimeline:
    """Align vehicle speed/RPM/gear references to dense post-run windows."""

    effective_config = config or VehicleReferenceTimelineConfig()
    _validate_config(effective_config)
    window_rows = _window_rows(windows)
    sample_rows = sorted(
        (sample for sample in samples if sample.t_s is not None and isfinite(sample.t_s)),
        key=lambda sample: float(sample.t_s or 0.0),
    )
    sample_rate_inconsistent = _sample_rate_inconsistent(metadata=metadata, samples=sample_rows)
    order_spec = metadata.order_reference_spec
    points = tuple(
        _build_point(
            run_id=run_id,
            window=window,
            samples=sample_rows,
            metadata=metadata,
            order_spec=order_spec,
            sample_rate_inconsistent=sample_rate_inconsistent,
            config=effective_config,
        )
        for window in window_rows
    )
    return VehicleReferenceTimeline(run_id=run_id, config=effective_config, points=points)


def vehicle_reference_debug_fixtures(
    timeline: VehicleReferenceTimeline,
) -> tuple[VehicleReferenceDebugFixture, ...]:
    """Return compact reference rows reusable by later order-tracking tests."""

    return tuple(
        VehicleReferenceDebugFixture(
            window_index=point.window_index,
            t_s=point.window_center_t_s,
            speed_kmh=point.speed_kmh,
            wheel_hz=point.wheel_hz,
            driveshaft_hz=point.driveshaft_hz,
            engine_hz=point.engine_hz,
            unavailable_reasons=point.unavailable_reasons,
        )
        for point in timeline.points
    )


def _validate_config(config: VehicleReferenceTimelineConfig) -> None:
    if config.max_interpolation_gap_s < 0:
        raise ValueError("vehicle reference timeline requires max_interpolation_gap_s >= 0")
    if config.max_stale_sample_age_s < 0:
        raise ValueError("vehicle reference timeline requires max_stale_sample_age_s >= 0")


def _window_rows(
    windows: (
        PostRunDenseStftResult | Iterable[PostRunStftFrame] | Iterable[WholeRunWindowDescriptor]
    ),
) -> tuple[WholeRunWindowDescriptor, ...]:
    if isinstance(windows, PostRunDenseStftResult):
        iterable: Iterable[PostRunStftFrame | WholeRunWindowDescriptor] = windows.frames
    else:
        iterable = windows
    by_index: dict[int, WholeRunWindowDescriptor] = {}
    for item in iterable:
        if isinstance(item, PostRunStftFrame):
            sample_end = item.requested_sample_start + item.requested_sample_count
            descriptor = WholeRunWindowDescriptor(
                window_index=item.window_index,
                sample_start=item.requested_sample_start,
                sample_end=sample_end,
                center_sample=item.requested_sample_start + (item.requested_sample_count // 2),
                start_t_s=item.window_start_t_s,
                end_t_s=item.window_end_t_s,
                center_t_s=item.window_center_t_s,
            )
        else:
            descriptor = item
        by_index.setdefault(descriptor.window_index, descriptor)
    return tuple(by_index[index] for index in sorted(by_index))


def _build_point(
    *,
    run_id: str,
    window: WholeRunWindowDescriptor,
    samples: Sequence[SensorFrame],
    metadata: RunMetadata,
    order_spec: OrderReferenceSpec | None,
    sample_rate_inconsistent: bool,
    config: VehicleReferenceTimelineConfig,
) -> VehicleReferencePoint:
    center_t = window.center_t_s
    reasons: list[VehicleReferenceUnavailableReason] = []
    if not samples:
        _append_unique_reason(reasons, "no_samples")
    if sample_rate_inconsistent:
        _append_unique_reason(reasons, "inconsistent_sample_rate")
    speed = _aligned_value(
        _speed_values(samples),
        center_t,
        config=config,
        missing_reason="missing_speed",
        stale_reason="stale_speed",
        allow_interpolation=True,
    )
    rpm = _aligned_value(
        _sample_values(samples, attr="engine_rpm", source_attr="engine_rpm_source"),
        center_t,
        config=config,
        missing_reason="missing_rpm",
        stale_reason="missing_rpm",
        allow_interpolation=True,
    )
    gear = _aligned_value(
        _sample_values(samples, attr="gear"),
        center_t,
        config=config,
        missing_reason="missing_gear",
        stale_reason="missing_gear",
        allow_interpolation=False,
    )
    final_drive = _aligned_value(
        _sample_values(samples, attr="final_drive_ratio"),
        center_t,
        config=config,
        missing_reason="unknown_final_drive",
        stale_reason="unknown_final_drive",
        allow_interpolation=False,
    )
    if (
        final_drive.value is None
        and final_drive.reason != "ambiguous_gap"
        and order_spec is not None
        and order_spec.final_drive_ratio > 0
    ):
        final_drive = _AlignedValue(
            value=order_spec.final_drive_ratio,
            source="settings",
            quality="sampled",
        )
    if (
        gear.value is None
        and gear.reason != "ambiguous_gap"
        and order_spec is not None
        and order_spec.current_gear_ratio > 0
    ):
        gear = _AlignedValue(
            value=order_spec.current_gear_ratio,
            source="settings",
            quality="sampled",
        )
    for aligned in (speed, rpm, gear, final_drive):
        if aligned.reason is not None:
            _append_unique_reason(reasons, aligned.reason)
    wheel_hz = _wheel_hz(order_spec=order_spec, speed_kmh=speed.value)
    if speed.value is not None and wheel_hz is None:
        _append_unique_reason(reasons, "unknown_tire")
    driveshaft_hz = _driveshaft_hz(wheel_hz=wheel_hz, final_drive_ratio=final_drive.value)
    if wheel_hz is not None and driveshaft_hz is None:
        _append_unique_reason(reasons, "unknown_final_drive")
    engine_hz = _engine_hz(
        engine_rpm=rpm.value,
        driveshaft_hz=driveshaft_hz,
        gear_ratio=gear.value,
    )
    if driveshaft_hz is not None and engine_hz is None:
        _append_unique_reason(reasons, "missing_gear")
    return VehicleReferencePoint(
        run_id=run_id,
        window_index=window.window_index,
        window_start_t_s=window.start_t_s,
        window_end_t_s=window.end_t_s,
        window_center_t_s=center_t,
        speed_kmh=speed.value,
        speed_source=speed.source,
        speed_quality=speed.quality,
        engine_rpm=rpm.value,
        engine_rpm_source=rpm.source,
        engine_rpm_quality=rpm.quality,
        gear_ratio=gear.value,
        gear_quality=gear.quality,
        final_drive_ratio=final_drive.value,
        final_drive_quality=final_drive.quality,
        wheel_hz=wheel_hz,
        driveshaft_hz=driveshaft_hz,
        engine_hz=engine_hz,
        wheel_uncertainty_pct=(
            order_spec.wheel_uncertainty_pct
            if order_spec is not None and wheel_hz is not None
            else None
        ),
        driveshaft_uncertainty_pct=(
            order_spec.drive_uncertainty_pct
            if order_spec is not None and driveshaft_hz is not None
            else None
        ),
        engine_uncertainty_pct=(
            order_spec.engine_uncertainty_pct
            if order_spec is not None and engine_hz is not None
            else None
        ),
        unavailable_reasons=tuple(reasons),
    )


def _aligned_value(
    values: Sequence[_TimedValue],
    t_s: float,
    *,
    config: VehicleReferenceTimelineConfig,
    missing_reason: VehicleReferenceUnavailableReason,
    stale_reason: VehicleReferenceUnavailableReason,
    allow_interpolation: bool,
) -> _AlignedValue:
    if not values:
        return _AlignedValue(None, None, "unavailable", missing_reason)
    before = _last_at_or_before(values, t_s)
    after = _first_at_or_after(values, t_s)
    exact = before if before is not None and abs(before.t_s - t_s) <= 1e-9 else None
    if exact is not None:
        return _AlignedValue(exact.value, exact.source, "sampled")
    if before is not None and after is not None:
        gap_s = after.t_s - before.t_s
        if gap_s <= config.max_interpolation_gap_s:
            if before.source != after.source:
                return _nearest_or_unavailable(values, t_s, config=config, reason="ambiguous_gap")
            if allow_interpolation:
                fraction = (t_s - before.t_s) / gap_s if gap_s > 0 else 0.0
                value = before.value + ((after.value - before.value) * fraction)
                return _AlignedValue(value, before.source, "interpolated")
            if before.value == after.value:
                return _AlignedValue(before.value, before.source, "sampled")
            return _nearest_or_unavailable(values, t_s, config=config, reason="ambiguous_gap")
    return _nearest_or_unavailable(values, t_s, config=config, reason=stale_reason)


def _nearest_or_unavailable(
    values: Sequence[_TimedValue],
    t_s: float,
    *,
    config: VehicleReferenceTimelineConfig,
    reason: VehicleReferenceUnavailableReason,
) -> _AlignedValue:
    nearest = min(values, key=lambda value: abs(value.t_s - t_s))
    if abs(nearest.t_s - t_s) <= config.max_stale_sample_age_s and reason != "ambiguous_gap":
        return _AlignedValue(nearest.value, nearest.source, "sampled")
    return _AlignedValue(None, None, "unavailable", reason)


def _speed_values(samples: Sequence[SensorFrame]) -> tuple[_TimedValue, ...]:
    values: list[_TimedValue] = []
    for sample in samples:
        t_s = float(sample.t_s or 0.0)
        speed = _finite_positive_or_zero(sample.speed_kmh)
        source = sample.speed_source or None
        if speed is None:
            speed = _finite_positive_or_zero(sample.gps_speed_kmh)
            source = "gps" if speed is not None else source
        if speed is not None:
            values.append(_TimedValue(t_s=t_s, value=speed, source=source))
    return tuple(values)


def _sample_values(
    samples: Sequence[SensorFrame],
    *,
    attr: str,
    source_attr: str | None = None,
) -> tuple[_TimedValue, ...]:
    values: list[_TimedValue] = []
    for sample in samples:
        value = _finite_positive_or_zero(getattr(sample, attr))
        if value is None:
            continue
        source = getattr(sample, source_attr) if source_attr is not None else None
        values.append(
            _TimedValue(
                t_s=float(sample.t_s or 0.0),
                value=value,
                source=str(source) if source else None,
            )
        )
    return tuple(values)


def _sample_rate_inconsistent(
    *,
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
) -> bool:
    sample_rates = {
        int(sample.sample_rate_hz)
        for sample in samples
        if sample.sample_rate_hz is not None and sample.sample_rate_hz > 0
    }
    if len(sample_rates) > 1:
        return True
    metadata_rate = metadata.raw_sample_rate_hz or metadata.configured_raw_sample_rate_hz
    if metadata_rate is None or not sample_rates:
        return False
    return int(metadata_rate) not in sample_rates


def _wheel_hz(*, order_spec: OrderReferenceSpec | None, speed_kmh: float | None) -> float | None:
    if order_spec is None or speed_kmh is None:
        return None
    return order_spec.wheel_hz_from_speed_kmh(speed_kmh)


def _driveshaft_hz(
    *,
    wheel_hz: float | None,
    final_drive_ratio: float | None,
) -> float | None:
    if wheel_hz is None or final_drive_ratio is None or final_drive_ratio <= 0:
        return None
    driveshaft_hz = wheel_hz * final_drive_ratio
    return driveshaft_hz if isfinite(driveshaft_hz) and driveshaft_hz > 0 else None


def _engine_hz(
    *,
    engine_rpm: float | None,
    driveshaft_hz: float | None,
    gear_ratio: float | None,
) -> float | None:
    if engine_rpm is not None and engine_rpm > 0:
        engine_hz = engine_rpm / 60.0
        return engine_hz if isfinite(engine_hz) else None
    if driveshaft_hz is None or gear_ratio is None or gear_ratio <= 0:
        return None
    engine_hz = driveshaft_hz * gear_ratio
    return engine_hz if isfinite(engine_hz) and engine_hz > 0 else None


def _last_at_or_before(values: Sequence[_TimedValue], t_s: float) -> _TimedValue | None:
    for value in reversed(values):
        if value.t_s <= t_s:
            return value
    return None


def _first_at_or_after(values: Sequence[_TimedValue], t_s: float) -> _TimedValue | None:
    for value in values:
        if value.t_s >= t_s:
            return value
    return None


def _finite_positive_or_zero(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value_float = float(value)
    if not isfinite(value_float) or value_float < 0:
        return None
    return value_float


def _append_unique_reason(
    reasons: list[VehicleReferenceUnavailableReason],
    reason: VehicleReferenceUnavailableReason,
) -> None:
    if reason not in reasons:
        reasons.append(reason)
