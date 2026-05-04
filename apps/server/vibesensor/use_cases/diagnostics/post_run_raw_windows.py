"""Streaming raw waveform window access for post-run diagnostics."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureManifest,
    RawCaptureSensorManifest,
    RawCaptureSensorRange,
)
from vibesensor.shared.types.run_schema import RunMetadata, RunSensorMetadata
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunWindowDescriptor,
    WholeRunWindowPolicy,
)

_SUPPORTED_RAW_CAPTURE_SCHEMA_VERSION = 7
_SUPPORTED_RAW_CAPTURE_STORAGE_TYPE = "run-directory-v1"
_SUPPORTED_RAW_CAPTURE_MODE = "full_run"
_AXIS_COUNT = 3

type PostRunRawWindowWarningCode = Literal[
    "missing_run_metadata",
    "missing_raw_capture_manifest",
    "manifest_run_id_mismatch",
    "unsupported_schema_version",
    "unsupported_storage_type",
    "unsupported_capture_mode",
    "missing_sensor_identity",
    "missing_sensor_location",
    "missing_requested_sensor",
    "missing_sidecar",
    "invalid_sample_rate",
    "sample_rate_mismatch",
    "sample_rate_unverified",
    "timestamp_gap",
    "invalid_axis_data",
    "low_sample_count",
]

type PostRunRawWindowDataQualityFlag = Literal[
    "partial_window",
    "timestamp_gap",
    "missing_samples",
    "low_sample_count",
    "invalid_axis_data",
    "sample_rate_mismatch",
    "sample_rate_unverified",
    "missing_sensor_location",
    "missing_sidecar",
]


class PostRunRawWindowRepository(Protocol):
    async def aget_run_metadata(self, run_id: str) -> RunMetadata | None: ...

    async def aget_raw_capture_manifest(self, run_id: str) -> RawCaptureManifest | None: ...

    async def aload_raw_capture_sensor_range(
        self,
        run_id: str,
        client_id: str,
        *,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None: ...


@dataclass(frozen=True, slots=True)
class PostRunRawWindowWarning:
    """Structured non-fatal warning from raw post-run window access."""

    code: PostRunRawWindowWarningCode
    message: str
    sensor_id: str | None = None
    window_index: int | None = None


@dataclass(frozen=True, slots=True)
class PostRunRawWindowIteratorConfig:
    """Configurable post-run window policy.

    If ``window_size_s`` or ``overlap_pct`` is omitted, the persisted run metadata
    supplies the canonical FFT window size and feature stride.
    """

    window_size_s: float | None = None
    overlap_pct: float | None = None
    min_valid_samples_pct: float = 1.0
    sensor_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PostRunRawWindowPlan:
    """Deterministic raw-window graph over one raw-capture artifact bundle."""

    policy: WholeRunWindowPolicy
    coverage_sample_start: int
    coverage_sample_end: int
    windows: tuple[WholeRunWindowDescriptor, ...]
    min_valid_samples_pct: float

    @property
    def total_sample_count(self) -> int:
        return max(0, self.coverage_sample_end - self.coverage_sample_start)

    @property
    def total_window_count(self) -> int:
        return len(self.windows)

    @property
    def min_valid_samples(self) -> int:
        return max(
            1,
            int(math.ceil(self.policy.window_size_samples * self.min_valid_samples_pct)),
        )


@dataclass(frozen=True, slots=True)
class PostRunRawSensorWindow:
    """One sensor's raw axis arrays for one post-run analysis window."""

    run_id: str
    client_id: str
    location: str
    window: WholeRunWindowDescriptor
    sample_rate_hz: int
    axis_x_i16: npt.NDArray[np.int16]
    axis_y_i16: npt.NDArray[np.int16]
    axis_z_i16: npt.NDArray[np.int16]
    requested_sample_start: int
    requested_sample_count: int
    returned_sample_start: int | None
    returned_sample_count: int
    data_quality_flags: tuple[PostRunRawWindowDataQualityFlag, ...]

    @property
    def start_t_s(self) -> float:
        return self.window.start_t_s

    @property
    def end_t_s(self) -> float:
        return self.window.end_t_s


@dataclass(frozen=True, slots=True)
class PostRunRawWindow:
    """Run-level DTO for one deterministic window across selected sensors."""

    run_id: str
    window: WholeRunWindowDescriptor
    sensors: tuple[PostRunRawSensorWindow, ...]
    warnings: tuple[PostRunRawWindowWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class PostRunRawWindowIterator:
    """Prepared streaming iterator over raw-capture window ranges."""

    repository: PostRunRawWindowRepository
    run_id: str
    metadata: RunMetadata | None
    manifest: RawCaptureManifest | None
    plan: PostRunRawWindowPlan | None
    sensors: tuple[RawCaptureSensorManifest, ...]
    warnings: tuple[PostRunRawWindowWarning, ...]
    config: PostRunRawWindowIteratorConfig

    async def iter_windows(self) -> AsyncIterator[PostRunRawWindow]:
        """Yield raw windows by reading only the needed sensor ranges."""

        if self.plan is None:
            return
        for window in self.plan.windows:
            sensor_windows: list[PostRunRawSensorWindow] = []
            window_warnings: list[PostRunRawWindowWarning] = []
            for sensor in self.sensors:
                raw_range = await self.repository.aload_raw_capture_sensor_range(
                    self.run_id,
                    sensor.client_id,
                    sample_start=window.sample_start,
                    sample_count=window.sample_count,
                )
                sensor_window, sensor_warnings = _build_sensor_window(
                    run_id=self.run_id,
                    metadata=self.metadata,
                    window=window,
                    plan=self.plan,
                    sensor=sensor,
                    raw_range=raw_range,
                )
                sensor_windows.append(sensor_window)
                window_warnings.extend(sensor_warnings)
            yield PostRunRawWindow(
                run_id=self.run_id,
                window=window,
                sensors=tuple(sensor_windows),
                warnings=tuple(window_warnings),
            )


async def prepare_post_run_raw_window_iterator(
    repository: PostRunRawWindowRepository,
    run_id: str,
    *,
    config: PostRunRawWindowIteratorConfig | None = None,
) -> PostRunRawWindowIterator:
    """Prepare manifest validation and window planning for one post-run raw capture."""

    effective_config = config or PostRunRawWindowIteratorConfig()
    _validate_config(effective_config)
    metadata = await repository.aget_run_metadata(run_id)
    warnings: list[PostRunRawWindowWarning] = []
    if metadata is None:
        warnings.append(
            PostRunRawWindowWarning(
                code="missing_run_metadata",
                message=f"run {run_id} has no metadata row",
            )
        )
        return _empty_iterator(repository, run_id, effective_config, warnings)

    manifest = await repository.aget_raw_capture_manifest(run_id)
    if manifest is None:
        warnings.append(
            PostRunRawWindowWarning(
                code="missing_raw_capture_manifest",
                message=f"run {run_id} has no raw-capture manifest",
            )
        )
        return _empty_iterator(
            repository,
            run_id,
            effective_config,
            warnings,
            metadata=metadata,
        )

    warnings.extend(_validate_manifest(run_id=run_id, manifest=manifest))
    if any(_fatal_manifest_warning(warning) for warning in warnings):
        return _empty_iterator(
            repository,
            run_id,
            effective_config,
            warnings,
            metadata=metadata,
            manifest=manifest,
        )

    sensors = _select_sensors(manifest, effective_config.sensor_ids, warnings)
    warnings.extend(_validate_sensors(metadata=metadata, sensors=sensors))
    plan = _build_plan(
        metadata=metadata,
        sensors=sensors,
        config=effective_config,
        warnings=warnings,
    )
    return PostRunRawWindowIterator(
        repository=repository,
        run_id=run_id,
        metadata=metadata,
        manifest=manifest,
        plan=plan,
        sensors=sensors,
        warnings=tuple(warnings),
        config=effective_config,
    )


def _empty_iterator(
    repository: PostRunRawWindowRepository,
    run_id: str,
    config: PostRunRawWindowIteratorConfig,
    warnings: Sequence[PostRunRawWindowWarning],
    *,
    metadata: RunMetadata | None = None,
    manifest: RawCaptureManifest | None = None,
) -> PostRunRawWindowIterator:
    return PostRunRawWindowIterator(
        repository=repository,
        run_id=run_id,
        metadata=metadata,
        manifest=manifest,
        plan=None,
        sensors=(),
        warnings=tuple(warnings),
        config=config,
    )


def _validate_manifest(
    *,
    run_id: str,
    manifest: RawCaptureManifest,
) -> tuple[PostRunRawWindowWarning, ...]:
    warnings: list[PostRunRawWindowWarning] = []
    if manifest.run_id != run_id:
        warnings.append(
            PostRunRawWindowWarning(
                code="manifest_run_id_mismatch",
                message=(
                    f"raw-capture manifest run_id {manifest.run_id!r} does not match {run_id!r}"
                ),
            )
        )
    if manifest.schema_version != _SUPPORTED_RAW_CAPTURE_SCHEMA_VERSION:
        warnings.append(
            PostRunRawWindowWarning(
                code="unsupported_schema_version",
                message=(
                    f"raw-capture schema {manifest.schema_version} is not supported; "
                    f"expected {_SUPPORTED_RAW_CAPTURE_SCHEMA_VERSION}"
                ),
            )
        )
    if manifest.storage_type != _SUPPORTED_RAW_CAPTURE_STORAGE_TYPE:
        warnings.append(
            PostRunRawWindowWarning(
                code="unsupported_storage_type",
                message=f"raw-capture storage type {manifest.storage_type!r} is not supported",
            )
        )
    if manifest.capture_mode != _SUPPORTED_RAW_CAPTURE_MODE:
        warnings.append(
            PostRunRawWindowWarning(
                code="unsupported_capture_mode",
                message=f"raw-capture mode {manifest.capture_mode!r} is not supported",
            )
        )
    return tuple(warnings)


def _fatal_manifest_warning(warning: PostRunRawWindowWarning) -> bool:
    return warning.code in {
        "manifest_run_id_mismatch",
        "unsupported_schema_version",
        "unsupported_storage_type",
        "unsupported_capture_mode",
    }


def _select_sensors(
    manifest: RawCaptureManifest,
    requested_sensor_ids: tuple[str, ...],
    warnings: list[PostRunRawWindowWarning],
) -> tuple[RawCaptureSensorManifest, ...]:
    sensors_by_id = {
        sensor.client_id: sensor for sensor in manifest.sensors if sensor.client_id.strip()
    }
    if not requested_sensor_ids:
        return tuple(sorted(sensors_by_id.values(), key=lambda sensor: sensor.client_id))

    selected: list[RawCaptureSensorManifest] = []
    for sensor_id in requested_sensor_ids:
        sensor = sensors_by_id.get(sensor_id)
        if sensor is None:
            warnings.append(
                PostRunRawWindowWarning(
                    code="missing_requested_sensor",
                    message=f"requested raw-capture sensor {sensor_id!r} is not in the manifest",
                    sensor_id=sensor_id,
                )
            )
            continue
        selected.append(sensor)
    return tuple(selected)


def _validate_sensors(
    *,
    metadata: RunMetadata,
    sensors: Sequence[RawCaptureSensorManifest],
) -> tuple[PostRunRawWindowWarning, ...]:
    warnings: list[PostRunRawWindowWarning] = []
    metadata_sample_rate_hz = int(metadata.raw_sample_rate_hz or 0)
    for sensor in sensors:
        if not sensor.client_id.strip():
            warnings.append(
                PostRunRawWindowWarning(
                    code="missing_sensor_identity",
                    message="raw-capture manifest contains a sensor without an identity",
                )
            )
        if sensor.sample_rate_hz <= 0:
            warnings.append(
                PostRunRawWindowWarning(
                    code="invalid_sample_rate",
                    message=(
                        f"sensor {sensor.client_id} has invalid "
                        f"sample_rate_hz={sensor.sample_rate_hz}"
                    ),
                    sensor_id=sensor.client_id,
                )
            )
        if metadata_sample_rate_hz > 0 and sensor.sample_rate_hz != metadata_sample_rate_hz:
            warnings.append(
                PostRunRawWindowWarning(
                    code="sample_rate_mismatch",
                    message=(
                        f"sensor {sensor.client_id} sample rate {sensor.sample_rate_hz} "
                        f"does not match run metadata {metadata_sample_rate_hz}"
                    ),
                    sensor_id=sensor.client_id,
                )
            )
        if sensor.sample_rate_unverified:
            warnings.append(
                PostRunRawWindowWarning(
                    code="sample_rate_unverified",
                    message=(
                        f"sensor {sensor.client_id} sample rate proof is "
                        f"{sensor.sample_rate_proof_state}"
                    ),
                    sensor_id=sensor.client_id,
                )
            )
        snapshot = metadata.sensor_snapshot_for(sensor.client_id)
        if snapshot is None or not snapshot.location_code.strip():
            warnings.append(
                PostRunRawWindowWarning(
                    code="missing_sensor_location",
                    message=f"sensor {sensor.client_id} has no run metadata location snapshot",
                    sensor_id=sensor.client_id,
                )
            )
    return tuple(warnings)


def _build_plan(
    *,
    metadata: RunMetadata,
    sensors: Sequence[RawCaptureSensorManifest],
    config: PostRunRawWindowIteratorConfig,
    warnings: list[PostRunRawWindowWarning],
) -> PostRunRawWindowPlan | None:
    if not sensors:
        return None
    policy = _resolve_policy(metadata=metadata, config=config)
    total_sample_count = max(max(0, sensor.sample_count) for sensor in sensors)
    if total_sample_count <= 0:
        return PostRunRawWindowPlan(
            policy=policy,
            coverage_sample_start=0,
            coverage_sample_end=0,
            windows=(),
            min_valid_samples_pct=config.min_valid_samples_pct,
        )
    min_valid_samples = max(
        1,
        int(math.ceil(policy.window_size_samples * config.min_valid_samples_pct)),
    )
    windows: list[WholeRunWindowDescriptor] = []
    for sample_start in range(0, total_sample_count, policy.stride_samples):
        remaining_samples = total_sample_count - sample_start
        if remaining_samples < min_valid_samples:
            break
        windows.append(
            WholeRunWindowDescriptor.from_policy(
                window_index=len(windows),
                sample_start=sample_start,
                policy=policy,
            )
        )
    if not windows and total_sample_count > 0:
        warnings.append(
            PostRunRawWindowWarning(
                code="low_sample_count",
                message=(
                    f"run has {total_sample_count} raw sample(s), below the "
                    f"{min_valid_samples} sample minimum for one window"
                ),
            )
        )
    return PostRunRawWindowPlan(
        policy=policy,
        coverage_sample_start=0,
        coverage_sample_end=total_sample_count,
        windows=tuple(windows),
        min_valid_samples_pct=config.min_valid_samples_pct,
    )


def _resolve_policy(
    *,
    metadata: RunMetadata,
    config: PostRunRawWindowIteratorConfig,
) -> WholeRunWindowPolicy:
    _validate_config(config)
    sample_rate_hz = int(metadata.raw_sample_rate_hz or 0)
    if sample_rate_hz <= 0:
        raise ValueError("post-run raw window iterator requires raw_sample_rate_hz")

    if config.window_size_s is None:
        window_size_samples = int(metadata.fft_window_size_samples or 0)
        if window_size_samples <= 0:
            raise ValueError("post-run raw window iterator requires fft_window_size_samples")
    else:
        raw_window_samples = config.window_size_s * float(sample_rate_hz)
        window_size_samples = int(round(raw_window_samples))
        if window_size_samples <= 0 or not math.isclose(
            raw_window_samples,
            float(window_size_samples),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "post-run raw window iterator requires window_size_s * raw_sample_rate_hz "
                "to resolve to an integral sample count"
            )

    if config.overlap_pct is None:
        feature_interval_s = float(metadata.feature_interval_s or 0.0)
        if feature_interval_s <= 0.0:
            raise ValueError("post-run raw window iterator requires feature_interval_s")
        raw_stride_samples = feature_interval_s * float(sample_rate_hz)
        stride_samples = int(round(raw_stride_samples))
        if stride_samples <= 0 or not math.isclose(
            raw_stride_samples,
            float(stride_samples),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "post-run raw window iterator requires feature_interval_s * raw_sample_rate_hz "
                "to resolve to an integral sample stride"
            )
    else:
        stride_samples = int(round(window_size_samples * (1.0 - config.overlap_pct)))
        feature_interval_s = float(stride_samples) / float(sample_rate_hz)

    if stride_samples <= 0 or stride_samples > window_size_samples:
        raise ValueError("post-run raw window iterator requires 0 < stride <= window size")
    return WholeRunWindowPolicy(
        sample_rate_hz=sample_rate_hz,
        window_size_samples=window_size_samples,
        stride_samples=stride_samples,
        overlap_samples=window_size_samples - stride_samples,
        feature_interval_s=feature_interval_s,
    )


def _validate_config(config: PostRunRawWindowIteratorConfig) -> None:
    if config.window_size_s is not None and config.window_size_s <= 0.0:
        raise ValueError("post-run raw window iterator requires window_size_s > 0")
    if config.overlap_pct is not None and not 0.0 <= config.overlap_pct < 1.0:
        raise ValueError("post-run raw window iterator requires 0 <= overlap_pct < 1")
    if not 0.0 < config.min_valid_samples_pct <= 1.0:
        raise ValueError("post-run raw window iterator requires 0 < min_valid_samples_pct <= 1")


def _build_sensor_window(
    *,
    run_id: str,
    metadata: RunMetadata | None,
    window: WholeRunWindowDescriptor,
    plan: PostRunRawWindowPlan,
    sensor: RawCaptureSensorManifest,
    raw_range: RawCaptureSensorRange | None,
) -> tuple[PostRunRawSensorWindow, tuple[PostRunRawWindowWarning, ...]]:
    warnings: list[PostRunRawWindowWarning] = []
    if raw_range is None:
        warnings.append(
            PostRunRawWindowWarning(
                code="missing_sidecar",
                message=f"raw sidecar for sensor {sensor.client_id} is missing",
                sensor_id=sensor.client_id,
                window_index=window.window_index,
            )
        )
        samples = np.empty((0, _AXIS_COUNT), dtype=np.int16)
        flags: list[PostRunRawWindowDataQualityFlag] = [
            "missing_sidecar",
            "missing_samples",
            "low_sample_count",
        ]
        returned_sample_start = None
    else:
        samples = raw_range.samples_i16
        flags = _quality_flags(
            metadata=metadata,
            plan=plan,
            sensor=sensor,
            raw_range=raw_range,
            warnings=warnings,
            window_index=window.window_index,
        )
        returned_sample_start = raw_range.returned_sample_start

    axis_x, axis_y, axis_z = _axis_arrays(samples)
    if samples.ndim != 2 or samples.shape[1] != _AXIS_COUNT:
        _append_unique_flag(flags, "invalid_axis_data")
    location = _sensor_location(metadata, sensor.client_id)
    if not location:
        _append_unique_flag(flags, "missing_sensor_location")
    sensor_window = PostRunRawSensorWindow(
        run_id=run_id,
        client_id=sensor.client_id,
        location=location,
        window=window,
        sample_rate_hz=sensor.sample_rate_hz,
        axis_x_i16=axis_x,
        axis_y_i16=axis_y,
        axis_z_i16=axis_z,
        requested_sample_start=window.sample_start,
        requested_sample_count=window.sample_count,
        returned_sample_start=returned_sample_start,
        returned_sample_count=int(axis_x.shape[0]),
        data_quality_flags=tuple(flags),
    )
    return sensor_window, tuple(warnings)


def _quality_flags(
    *,
    metadata: RunMetadata | None,
    plan: PostRunRawWindowPlan,
    sensor: RawCaptureSensorManifest,
    raw_range: RawCaptureSensorRange,
    warnings: list[PostRunRawWindowWarning],
    window_index: int,
) -> list[PostRunRawWindowDataQualityFlag]:
    flags: list[PostRunRawWindowDataQualityFlag] = []
    if raw_range.coverage_state != "full":
        _append_unique_flag(flags, "partial_window")
    if raw_range.coverage_state in {"missing", "empty"} or (
        raw_range.returned_sample_count < raw_range.requested_sample_count
    ):
        _append_unique_flag(flags, "missing_samples")
    if raw_range.returned_sample_count < plan.min_valid_samples:
        _append_unique_flag(flags, "low_sample_count")
        warnings.append(
            PostRunRawWindowWarning(
                code="low_sample_count",
                message=(
                    f"sensor {sensor.client_id} returned {raw_range.returned_sample_count} "
                    f"sample(s), below the {plan.min_valid_samples} sample window threshold"
                ),
                sensor_id=sensor.client_id,
                window_index=window_index,
            )
        )
    if sensor.sample_rate_unverified:
        _append_unique_flag(flags, "sample_rate_unverified")
    metadata_sample_rate_hz = int(metadata.raw_sample_rate_hz or 0) if metadata else 0
    if metadata_sample_rate_hz > 0 and sensor.sample_rate_hz != metadata_sample_rate_hz:
        _append_unique_flag(flags, "sample_rate_mismatch")
    if _has_timestamp_gap(raw_range.chunks, sample_rate_hz=sensor.sample_rate_hz):
        _append_unique_flag(flags, "timestamp_gap")
        warnings.append(
            PostRunRawWindowWarning(
                code="timestamp_gap",
                message=f"sensor {sensor.client_id} has non-monotonic or gapped chunk timestamps",
                sensor_id=sensor.client_id,
                window_index=window_index,
            )
        )
    if raw_range.samples_i16.ndim != 2 or raw_range.samples_i16.shape[1] != _AXIS_COUNT:
        _append_unique_flag(flags, "invalid_axis_data")
        warnings.append(
            PostRunRawWindowWarning(
                code="invalid_axis_data",
                message=f"sensor {sensor.client_id} returned invalid raw axis data shape",
                sensor_id=sensor.client_id,
                window_index=window_index,
            )
        )
    return flags


def _append_unique_flag(
    flags: list[PostRunRawWindowDataQualityFlag],
    flag: PostRunRawWindowDataQualityFlag,
) -> None:
    if flag not in flags:
        flags.append(flag)


def _axis_arrays(
    samples: npt.NDArray[np.int16],
) -> tuple[npt.NDArray[np.int16], npt.NDArray[np.int16], npt.NDArray[np.int16]]:
    if samples.ndim != 2 or samples.shape[1] != _AXIS_COUNT:
        empty = np.empty((0,), dtype=np.int16)
        return empty, empty, empty
    return samples[:, 0], samples[:, 1], samples[:, 2]


def _sensor_location(metadata: RunMetadata | None, sensor_id: str) -> str:
    snapshot: RunSensorMetadata | None = (
        metadata.sensor_snapshot_for(sensor_id) if metadata is not None else None
    )
    return snapshot.location_code.strip() if snapshot is not None else ""


def _has_timestamp_gap(
    chunks: Sequence[RawCaptureChunkIndex],
    *,
    sample_rate_hz: int,
) -> bool:
    if sample_rate_hz <= 0 or len(chunks) < 2:
        return False
    sample_period_us = 1_000_000.0 / float(sample_rate_hz)
    tolerance_us = max(sample_period_us, 1_000.0)
    ordered = sorted(chunks, key=lambda chunk: chunk.sample_start)
    previous = ordered[0]
    for current in ordered[1:]:
        if current.t0_us < previous.t0_us:
            return True
        expected_delta_us = (current.sample_start - previous.sample_start) * sample_period_us
        actual_delta_us = current.t0_us - previous.t0_us
        if abs(actual_delta_us - expected_delta_us) > tolerance_us:
            return True
        previous = current
    return False
