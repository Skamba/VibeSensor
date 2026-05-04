"""Per-window order-frequency bands for dense post-run analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Literal

from vibesensor.domain import OrderReferenceSpec
from vibesensor.shared.order_bands import tolerance_for_order
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.whole_run_json_helpers import set_optional_value
from vibesensor.use_cases.diagnostics.post_run_vehicle_reference import (
    VehicleReferencePoint,
    VehicleReferenceTimeline,
    VehicleReferenceUnavailableReason,
)

type OrderBandSource = Literal["wheel", "driveshaft", "engine"]
type OrderBandUnavailableReason = (
    VehicleReferenceUnavailableReason
    | Literal[
        "missing_order_reference",
        "invalid_center",
        "outside_spectrum",
    ]
)

_DEFAULT_WHEEL_HARMONICS = (1, 2)
_DEFAULT_DRIVESHAFT_HARMONICS = (1, 2)
_DEFAULT_ENGINE_HARMONICS = (1, 2)

__all__ = [
    "OrderBand",
    "OrderBandSource",
    "OrderBandUnavailableReason",
    "OrderBandWindow",
    "PostRunOrderBandTimeline",
    "PostRunOrderBandsConfig",
    "build_post_run_order_band_timeline",
    "serialize_order_band_rows",
]


@dataclass(frozen=True, slots=True)
class PostRunOrderBandsConfig:
    """Order-band harmonics and output spectrum clamp."""

    wheel_harmonics: tuple[int, ...] = _DEFAULT_WHEEL_HARMONICS
    driveshaft_harmonics: tuple[int, ...] = _DEFAULT_DRIVESHAFT_HARMONICS
    engine_harmonics: tuple[int, ...] = _DEFAULT_ENGINE_HARMONICS
    min_frequency_hz: float = 0.0
    max_frequency_hz: float | None = None


@dataclass(frozen=True, slots=True)
class OrderBand:
    """One expected order-frequency band for one dense analysis window."""

    label: str
    source: OrderBandSource
    harmonic: int
    center_hz: float | None
    min_hz: float | None
    max_hz: float | None
    uncertainty_pct: float | None
    tolerance: float | None
    unavailable_reason: OrderBandUnavailableReason | None = None
    reference_source: str | None = None

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "label": self.label,
            "source": self.source,
            "harmonic": self.harmonic,
        }
        set_optional_value(payload, "center_hz", self.center_hz)
        set_optional_value(payload, "min_hz", self.min_hz)
        set_optional_value(payload, "max_hz", self.max_hz)
        set_optional_value(payload, "uncertainty_pct", self.uncertainty_pct)
        set_optional_value(payload, "tolerance", self.tolerance)
        set_optional_value(payload, "unavailable_reason", self.unavailable_reason)
        set_optional_value(payload, "reference_source", self.reference_source)
        return payload


@dataclass(frozen=True, slots=True)
class OrderBandWindow:
    """Order bands aligned to one vehicle-reference window."""

    run_id: str
    window_index: int
    window_start_t_s: float
    window_end_t_s: float
    window_center_t_s: float
    bands: tuple[OrderBand, ...]
    vehicle_unavailable_reasons: tuple[VehicleReferenceUnavailableReason, ...] = ()

    def to_json_object(self) -> JsonObject:
        return {
            "run_id": self.run_id,
            "window_index": self.window_index,
            "window_start_t_s": self.window_start_t_s,
            "window_end_t_s": self.window_end_t_s,
            "window_center_t_s": self.window_center_t_s,
            "vehicle_unavailable_reasons": list(self.vehicle_unavailable_reasons),
            "bands": [band.to_json_object() for band in self.bands],
        }


@dataclass(frozen=True, slots=True)
class PostRunOrderBandTimeline:
    """Dense-window order-band timeline."""

    run_id: str
    config: PostRunOrderBandsConfig
    windows: tuple[OrderBandWindow, ...]

    def window_for_index(self, window_index: int) -> OrderBandWindow | None:
        for window in self.windows:
            if window.window_index == window_index:
                return window
        return None

    def to_json_object(self) -> JsonObject:
        return {
            "run_id": self.run_id,
            "windows": [window.to_json_object() for window in self.windows],
        }


@dataclass(frozen=True, slots=True)
class _FamilyBandInput:
    source: OrderBandSource
    harmonics: tuple[int, ...]
    base_center_hz: float | None
    base_bandwidth_pct: float
    uncertainty_pct: float | None
    unavailable_reason: OrderBandUnavailableReason | None
    reference_source: str | None


def build_post_run_order_band_timeline(
    *,
    vehicle_timeline: VehicleReferenceTimeline,
    order_reference_spec: OrderReferenceSpec | None,
    config: PostRunOrderBandsConfig | None = None,
) -> PostRunOrderBandTimeline:
    """Build order-frequency bands for every POSTRUN-04 vehicle-reference window."""

    effective_config = config or PostRunOrderBandsConfig()
    _validate_config(effective_config)
    windows = tuple(
        _build_window(
            point=point,
            order_reference_spec=order_reference_spec,
            config=effective_config,
        )
        for point in vehicle_timeline.points
    )
    return PostRunOrderBandTimeline(
        run_id=vehicle_timeline.run_id,
        config=effective_config,
        windows=windows,
    )


def serialize_order_band_rows(timeline: PostRunOrderBandTimeline) -> tuple[JsonObject, ...]:
    """Flatten a band timeline into stable rows for later report/UI consumers."""

    rows: list[JsonObject] = []
    for window in timeline.windows:
        for band in window.bands:
            row: JsonObject = {
                "run_id": window.run_id,
                "window_index": window.window_index,
                "window_start_t_s": window.window_start_t_s,
                "window_end_t_s": window.window_end_t_s,
                "window_center_t_s": window.window_center_t_s,
            }
            row.update(band.to_json_object())
            rows.append(row)
    return tuple(rows)


def _validate_config(config: PostRunOrderBandsConfig) -> None:
    if not _harmonics_valid(config.wheel_harmonics):
        raise ValueError("wheel_harmonics must contain positive harmonic integers")
    if not _harmonics_valid(config.driveshaft_harmonics):
        raise ValueError("driveshaft_harmonics must contain positive harmonic integers")
    if not _harmonics_valid(config.engine_harmonics):
        raise ValueError("engine_harmonics must contain positive harmonic integers")
    if not isfinite(config.min_frequency_hz) or config.min_frequency_hz < 0:
        raise ValueError("min_frequency_hz must be finite and >= 0")
    if config.max_frequency_hz is not None and (
        not isfinite(config.max_frequency_hz) or config.max_frequency_hz < config.min_frequency_hz
    ):
        raise ValueError("max_frequency_hz must be finite and >= min_frequency_hz")


def _harmonics_valid(harmonics: Sequence[int]) -> bool:
    return bool(harmonics) and all(
        not isinstance(harmonic, bool) and isinstance(harmonic, int) and harmonic > 0
        for harmonic in harmonics
    )


def _build_window(
    *,
    point: VehicleReferencePoint,
    order_reference_spec: OrderReferenceSpec | None,
    config: PostRunOrderBandsConfig,
) -> OrderBandWindow:
    bands: list[OrderBand] = []
    for family in _family_inputs(
        point=point,
        order_reference_spec=order_reference_spec,
        config=config,
    ):
        bands.extend(
            _build_band(
                family=family,
                harmonic=harmonic,
                order_reference_spec=order_reference_spec,
                config=config,
            )
            for harmonic in family.harmonics
        )
    return OrderBandWindow(
        run_id=point.run_id,
        window_index=point.window_index,
        window_start_t_s=point.window_start_t_s,
        window_end_t_s=point.window_end_t_s,
        window_center_t_s=point.window_center_t_s,
        bands=tuple(bands),
        vehicle_unavailable_reasons=point.unavailable_reasons,
    )


def _family_inputs(
    *,
    point: VehicleReferencePoint,
    order_reference_spec: OrderReferenceSpec | None,
    config: PostRunOrderBandsConfig,
) -> tuple[_FamilyBandInput, ...]:
    if order_reference_spec is None:
        return (
            _missing_family("wheel", config.wheel_harmonics),
            _missing_family("driveshaft", config.driveshaft_harmonics),
            _missing_family("engine", config.engine_harmonics),
        )
    return (
        _FamilyBandInput(
            source="wheel",
            harmonics=config.wheel_harmonics,
            base_center_hz=point.wheel_hz,
            base_bandwidth_pct=order_reference_spec.wheel_bandwidth_pct,
            uncertainty_pct=point.wheel_uncertainty_pct,
            unavailable_reason=_reason_for_family(point, "wheel"),
            reference_source="speed+tire",
        ),
        _FamilyBandInput(
            source="driveshaft",
            harmonics=config.driveshaft_harmonics,
            base_center_hz=point.driveshaft_hz,
            base_bandwidth_pct=order_reference_spec.driveshaft_bandwidth_pct,
            uncertainty_pct=point.driveshaft_uncertainty_pct,
            unavailable_reason=_reason_for_family(point, "driveshaft"),
            reference_source="speed+tire+final_drive",
        ),
        _FamilyBandInput(
            source="engine",
            harmonics=config.engine_harmonics,
            base_center_hz=point.engine_hz,
            base_bandwidth_pct=order_reference_spec.engine_bandwidth_pct,
            uncertainty_pct=point.engine_uncertainty_pct,
            unavailable_reason=_reason_for_family(point, "engine"),
            reference_source=_engine_reference_source(point),
        ),
    )


def _missing_family(
    source: OrderBandSource,
    harmonics: tuple[int, ...],
) -> _FamilyBandInput:
    return _FamilyBandInput(
        source=source,
        harmonics=harmonics,
        base_center_hz=None,
        base_bandwidth_pct=0.0,
        uncertainty_pct=None,
        unavailable_reason="missing_order_reference",
        reference_source=None,
    )


def _build_band(
    *,
    family: _FamilyBandInput,
    harmonic: int,
    order_reference_spec: OrderReferenceSpec | None,
    config: PostRunOrderBandsConfig,
) -> OrderBand:
    label = f"{family.source}_{harmonic}x"
    unavailable_reason = family.unavailable_reason
    center_hz = _harmonic_center(family.base_center_hz, harmonic)
    if unavailable_reason is None and center_hz is None:
        unavailable_reason = "invalid_center"
    if unavailable_reason is not None or center_hz is None or order_reference_spec is None:
        return OrderBand(
            label=label,
            source=family.source,
            harmonic=harmonic,
            center_hz=center_hz,
            min_hz=None,
            max_hz=None,
            uncertainty_pct=family.uncertainty_pct,
            tolerance=None,
            unavailable_reason=unavailable_reason or "missing_order_reference",
            reference_source=family.reference_source,
        )
    tolerance = tolerance_for_order(
        family.base_bandwidth_pct,
        center_hz,
        family.uncertainty_pct or 0.0,
        min_abs_band_hz=order_reference_spec.min_abs_band_hz,
        max_band_half_width_pct=order_reference_spec.max_band_half_width_pct,
    )
    raw_min_hz = center_hz * (1.0 - tolerance)
    raw_max_hz = center_hz * (1.0 + tolerance)
    min_hz = max(config.min_frequency_hz, raw_min_hz)
    max_hz = raw_max_hz
    if config.max_frequency_hz is not None:
        max_hz = min(config.max_frequency_hz, max_hz)
    if max_hz < min_hz:
        return OrderBand(
            label=label,
            source=family.source,
            harmonic=harmonic,
            center_hz=center_hz,
            min_hz=None,
            max_hz=None,
            uncertainty_pct=family.uncertainty_pct,
            tolerance=tolerance,
            unavailable_reason="outside_spectrum",
            reference_source=family.reference_source,
        )
    return OrderBand(
        label=label,
        source=family.source,
        harmonic=harmonic,
        center_hz=center_hz,
        min_hz=min_hz,
        max_hz=max_hz,
        uncertainty_pct=family.uncertainty_pct,
        tolerance=tolerance,
        reference_source=family.reference_source,
    )


def _harmonic_center(base_center_hz: float | None, harmonic: int) -> float | None:
    if base_center_hz is None or harmonic <= 0:
        return None
    center_hz = base_center_hz * harmonic
    if not isfinite(center_hz) or center_hz <= 0:
        return None
    return center_hz


def _reason_for_family(
    point: VehicleReferencePoint,
    source: OrderBandSource,
) -> OrderBandUnavailableReason | None:
    if source == "wheel":
        if point.wheel_hz is not None:
            return None
        return _first_reason(
            point,
            (
                "unknown_tire",
                "ambiguous_gap",
                "stale_speed",
                "missing_speed",
                "no_samples",
            ),
            default="missing_speed",
        )
    if source == "driveshaft":
        if point.driveshaft_hz is not None:
            return None
        return _first_reason(
            point,
            (
                "unknown_final_drive",
                "unknown_tire",
                "ambiguous_gap",
                "stale_speed",
                "missing_speed",
                "no_samples",
            ),
            default="unknown_final_drive",
        )
    if point.engine_hz is not None:
        return None
    return _first_reason(
        point,
        (
            "missing_gear",
            "missing_rpm",
            "unknown_final_drive",
            "unknown_tire",
            "ambiguous_gap",
            "stale_speed",
            "missing_speed",
            "no_samples",
        ),
        default="missing_rpm",
    )


def _first_reason(
    point: VehicleReferencePoint,
    candidates: Sequence[VehicleReferenceUnavailableReason],
    *,
    default: VehicleReferenceUnavailableReason,
) -> VehicleReferenceUnavailableReason:
    for reason in candidates:
        if reason in point.unavailable_reasons:
            return reason
    return default


def _engine_reference_source(point: VehicleReferencePoint) -> str | None:
    if point.engine_hz is None:
        return None
    if point.engine_rpm is not None and point.engine_rpm > 0:
        return point.engine_rpm_source or "rpm"
    if point.driveshaft_hz is not None and point.gear_ratio is not None:
        return "speed+tire+final_drive+gear"
    return None
