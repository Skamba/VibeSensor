"""Dense post-run STFT over raw-window DTOs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from vibesensor.shared.constants.dsp import SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.shared.fft_analysis import (
    AXES,
    Axis,
    BoolArray,
    FftWindowFunction,
    FloatArray,
    IntIndexArray,
    compute_fft_spectrum,
    fft_frequency_slice,
    fft_window_values,
)
from vibesensor.shared.sensor_orientation import (
    AxisFrame,
    SignedAxis,
    estimate_gravity_axis,
    parse_mount_orientation,
    transform_axis_matrix_to_vehicle,
)
from vibesensor.use_cases.diagnostics.post_run_raw_windows import (
    PostRunRawSensorWindow,
    PostRunRawWindow,
    PostRunRawWindowDataQualityFlag,
)
from vibesensor.vibration_strength import StrengthPeak

type PostRunStftPartialWindowPolicy = Literal["mark", "skip", "zero_pad"]
type PostRunStftCoverageState = Literal["full", "partial", "missing", "invalid"]


@dataclass(frozen=True, slots=True)
class PostRunStftConfig:
    """Configuration for dense post-run spectral analysis.

    Window size and overlap are normally owned by the POSTRUN-01 raw-window
    iterator. ``fft_size_samples`` lets callers decouple FFT size from the raw
    window size when a later stage intentionally wants a different transform.
    """

    fft_size_samples: int | None = None
    window_function: FftWindowFunction = "hann"
    spectrum_min_hz: float = SPECTRUM_MIN_HZ
    spectrum_max_hz: float = SPECTRUM_MAX_HZ
    partial_window_policy: PostRunStftPartialWindowPolicy = "mark"
    accel_scale_g_per_lsb: float | None = None
    spike_filter_enabled: bool = False


@dataclass(frozen=True, slots=True)
class PostRunStftFrame:
    """One dense time-frequency frame for one sensor/window."""

    run_id: str
    client_id: str
    location: str
    window_index: int
    window_start_t_s: float
    window_end_t_s: float
    window_center_t_s: float
    sample_rate_hz: int
    requested_sample_start: int
    requested_sample_count: int
    returned_sample_start: int | None
    returned_sample_count: int
    coverage_state: PostRunStftCoverageState
    data_quality_flags: tuple[PostRunRawWindowDataQualityFlag, ...]
    mount_orientation: str | None
    axis_frame: AxisFrame
    gravity_axis: SignedAxis | None
    freq_hz: FloatArray
    spectrum_by_axis_amp_g: dict[Axis, FloatArray]
    combined_amp_g: FloatArray
    rms_by_axis_g: dict[Axis, float]
    p2p_by_axis_g: dict[Axis, float]
    dominant_freq_hz: float | None = None
    vibration_strength_db: float | None = None
    strength_peak_amp_g: float | None = None
    strength_floor_amp_g: float | None = None
    strength_bucket: str | None = None
    top_peaks: tuple[StrengthPeak, ...] = ()


@dataclass(frozen=True, slots=True)
class PostRunDenseStftResult:
    """In-memory dense STFT output for a batch of post-run windows."""

    config: PostRunStftConfig
    frames: tuple[PostRunStftFrame, ...]

    def frames_for_sensor(self, client_id: str) -> tuple[PostRunStftFrame, ...]:
        return tuple(frame for frame in self.frames if frame.client_id == client_id)


def compute_post_run_dense_stft(
    windows: Iterable[PostRunRawWindow],
    *,
    config: PostRunStftConfig | None = None,
) -> PostRunDenseStftResult:
    """Compute deterministic dense STFT frames from POSTRUN-01 raw-window DTOs."""

    effective_config = config or PostRunStftConfig()
    _validate_config(effective_config)
    frames: list[PostRunStftFrame] = []
    cache: dict[tuple[int, int, str, float, float], _FftContext] = {}
    for raw_window in windows:
        for sensor_window in raw_window.sensors:
            fft_size_samples = effective_config.fft_size_samples or (
                sensor_window.requested_sample_count
            )
            key = (
                int(sensor_window.sample_rate_hz),
                int(fft_size_samples),
                effective_config.window_function,
                float(effective_config.spectrum_min_hz),
                float(effective_config.spectrum_max_hz),
            )
            context = cache.get(key)
            if context is None:
                context = _build_fft_context(
                    sample_rate_hz=sensor_window.sample_rate_hz,
                    fft_size_samples=fft_size_samples,
                    config=effective_config,
                )
                cache[key] = context
            frame = _compute_sensor_frame(
                sensor_window=sensor_window,
                context=context,
                config=effective_config,
            )
            if frame is not None:
                frames.append(frame)
    return PostRunDenseStftResult(config=effective_config, frames=tuple(frames))


@dataclass(frozen=True, slots=True)
class _FftContext:
    fft_size_samples: int
    freq_hz: FloatArray
    valid_idx: IntIndexArray
    strength_range_mask: BoolArray
    fft_window: FloatArray
    fft_scale: float


def _validate_config(config: PostRunStftConfig) -> None:
    if config.fft_size_samples is not None and config.fft_size_samples <= 0:
        raise ValueError("post-run dense STFT requires fft_size_samples > 0")
    if config.spectrum_min_hz < 0:
        raise ValueError("post-run dense STFT requires spectrum_min_hz >= 0")
    if config.spectrum_max_hz < config.spectrum_min_hz:
        raise ValueError("post-run dense STFT requires spectrum_max_hz >= spectrum_min_hz")
    if config.accel_scale_g_per_lsb is not None and config.accel_scale_g_per_lsb <= 0:
        raise ValueError("post-run dense STFT requires accel_scale_g_per_lsb > 0")


def _build_fft_context(
    *,
    sample_rate_hz: int,
    fft_size_samples: int,
    config: PostRunStftConfig,
) -> _FftContext:
    if sample_rate_hz <= 0:
        return _FftContext(
            fft_size_samples=fft_size_samples,
            freq_hz=np.empty(0, dtype=np.float32),
            valid_idx=np.empty(0, dtype=np.intp),
            strength_range_mask=np.empty(0, dtype=np.bool_),
            fft_window=np.empty(0, dtype=np.float32),
            fft_scale=1.0,
        )
    fft_window = fft_window_values(
        fft_n=fft_size_samples,
        window_function=config.window_function,
    )
    freq_hz, valid_idx, strength_range_mask = fft_frequency_slice(
        fft_n=fft_size_samples,
        sample_rate_hz=sample_rate_hz,
        spectrum_min_hz=config.spectrum_min_hz,
        spectrum_max_hz=config.spectrum_max_hz,
    )
    return _FftContext(
        fft_size_samples=fft_size_samples,
        freq_hz=freq_hz,
        valid_idx=valid_idx,
        strength_range_mask=strength_range_mask,
        fft_window=fft_window,
        fft_scale=float(2.0 / max(1.0, float(np.sum(fft_window)))),
    )


def _compute_sensor_frame(
    *,
    sensor_window: PostRunRawSensorWindow,
    context: _FftContext,
    config: PostRunStftConfig,
) -> PostRunStftFrame | None:
    coverage_state = _coverage_state(sensor_window)
    if coverage_state == "missing" and config.partial_window_policy == "skip":
        return None
    if context.freq_hz.size == 0 or context.fft_window.size == 0:
        return _empty_frame(
            sensor_window=sensor_window,
            context=context,
            coverage_state="invalid",
        )
    axis_samples = _sensor_window_axis_matrix(sensor_window)
    if axis_samples is None:
        return _empty_frame(
            sensor_window=sensor_window,
            context=context,
            coverage_state="invalid",
        )
    prepared_samples = _prepare_fft_samples(
        axis_samples=axis_samples,
        fft_size_samples=context.fft_size_samples,
        coverage_state=coverage_state,
        partial_window_policy=config.partial_window_policy,
    )
    if prepared_samples is None:
        if config.partial_window_policy == "mark":
            return _empty_frame(
                sensor_window=sensor_window,
                context=context,
                coverage_state=coverage_state,
            )
        return None
    if config.accel_scale_g_per_lsb is not None:
        prepared_samples = prepared_samples * np.float32(config.accel_scale_g_per_lsb)
    gravity_axis = estimate_gravity_axis(prepared_samples)
    orientation = parse_mount_orientation(sensor_window.mount_orientation)
    axis_frame: AxisFrame = "sensor_local"
    if orientation is not None:
        prepared_samples = transform_axis_matrix_to_vehicle(prepared_samples, orientation)
        axis_frame = "vehicle"
    rms_by_axis_g, p2p_by_axis_g = _time_domain_metrics_by_axis(prepared_samples)
    fft_result = compute_fft_spectrum(
        prepared_samples,
        sensor_window.sample_rate_hz,
        fft_window=context.fft_window,
        fft_scale=context.fft_scale,
        freq_slice=context.freq_hz,
        valid_idx=context.valid_idx,
        strength_range_mask=context.strength_range_mask,
        spike_filter_enabled=config.spike_filter_enabled,
    )
    spectrum_by_axis = {
        axis: np.asarray(fft_result["spectrum_by_axis"][axis]["amp"], dtype=np.float32, copy=True)
        for axis in AXES
    }
    strength_metrics = fft_result["strength_metrics"]
    top_peaks = tuple(
        peak for peak in strength_metrics["top_peaks"] if peak["hz"] > 0 and peak["amp"] > 0
    )
    dominant_freq_hz = top_peaks[0]["hz"] if top_peaks else None
    return PostRunStftFrame(
        run_id=sensor_window.run_id,
        client_id=sensor_window.client_id,
        location=sensor_window.location,
        window_index=sensor_window.window.window_index,
        window_start_t_s=sensor_window.window.start_t_s,
        window_end_t_s=sensor_window.window.end_t_s,
        window_center_t_s=sensor_window.window.center_t_s,
        sample_rate_hz=sensor_window.sample_rate_hz,
        requested_sample_start=sensor_window.requested_sample_start,
        requested_sample_count=sensor_window.requested_sample_count,
        returned_sample_start=sensor_window.returned_sample_start,
        returned_sample_count=sensor_window.returned_sample_count,
        coverage_state=coverage_state,
        data_quality_flags=sensor_window.data_quality_flags,
        mount_orientation=sensor_window.mount_orientation,
        axis_frame=axis_frame,
        gravity_axis=gravity_axis,
        freq_hz=np.asarray(fft_result["freq_slice"], dtype=np.float32, copy=True),
        spectrum_by_axis_amp_g=spectrum_by_axis,
        combined_amp_g=np.asarray(fft_result["combined_amp"], dtype=np.float32, copy=True),
        rms_by_axis_g=rms_by_axis_g,
        p2p_by_axis_g=p2p_by_axis_g,
        dominant_freq_hz=dominant_freq_hz,
        vibration_strength_db=_float_or_none(strength_metrics.get("vibration_strength_db")),
        strength_peak_amp_g=_float_or_none(strength_metrics.get("peak_amp_g")),
        strength_floor_amp_g=_float_or_none(strength_metrics.get("noise_floor_amp_g")),
        strength_bucket=strength_metrics.get("strength_bucket"),
        top_peaks=top_peaks,
    )


def _coverage_state(sensor_window: PostRunRawSensorWindow) -> PostRunStftCoverageState:
    flags = set(sensor_window.data_quality_flags)
    if "invalid_axis_data" in flags:
        return "invalid"
    if "missing_sidecar" in flags or sensor_window.returned_sample_count <= 0:
        return "missing"
    if flags.intersection({"partial_window", "missing_samples", "low_sample_count"}):
        return "partial"
    return "full"


def _sensor_window_axis_matrix(sensor_window: PostRunRawSensorWindow) -> FloatArray | None:
    if (
        sensor_window.axis_x_i16.ndim != 1
        or sensor_window.axis_y_i16.ndim != 1
        or sensor_window.axis_z_i16.ndim != 1
    ):
        return None
    if not all(
        axis.shape == sensor_window.axis_x_i16.shape
        for axis in (sensor_window.axis_y_i16, sensor_window.axis_z_i16)
    ):
        return None
    return np.stack(
        [
            sensor_window.axis_x_i16.astype(np.float32, copy=False),
            sensor_window.axis_y_i16.astype(np.float32, copy=False),
            sensor_window.axis_z_i16.astype(np.float32, copy=False),
        ],
        axis=0,
    ).astype(np.float32, copy=False)


def _time_domain_metrics_by_axis(
    axis_samples: FloatArray,
) -> tuple[dict[Axis, float], dict[Axis, float]]:
    if axis_samples.ndim != 2 or axis_samples.shape[0] != len(AXES) or axis_samples.shape[1] == 0:
        zeros = {axis: 0.0 for axis in AXES}
        return zeros.copy(), zeros.copy()
    clean = np.nan_to_num(
        axis_samples,
        copy=True,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    ).astype(np.float32, copy=False)
    rms_values = np.sqrt(np.mean(np.square(clean, dtype=np.float64), axis=1))
    p2p_values = np.ptp(clean, axis=1)
    return (
        {axis: float(rms_values[index]) for index, axis in enumerate(AXES)},
        {axis: float(p2p_values[index]) for index, axis in enumerate(AXES)},
    )


def _prepare_fft_samples(
    *,
    axis_samples: FloatArray,
    fft_size_samples: int,
    coverage_state: PostRunStftCoverageState,
    partial_window_policy: PostRunStftPartialWindowPolicy,
) -> FloatArray | None:
    sample_count = int(axis_samples.shape[1])
    if sample_count == fft_size_samples and coverage_state in {"full", "partial"}:
        return axis_samples.copy()
    if coverage_state == "full" and sample_count > fft_size_samples:
        return axis_samples[:, :fft_size_samples].copy()
    if partial_window_policy == "skip":
        return None
    if partial_window_policy == "mark":
        return None
    padded = np.zeros((3, fft_size_samples), dtype=np.float32)
    copy_count = min(sample_count, fft_size_samples)
    if copy_count > 0:
        padded[:, :copy_count] = axis_samples[:, :copy_count]
    return padded


def _empty_frame(
    *,
    sensor_window: PostRunRawSensorWindow,
    context: _FftContext,
    coverage_state: PostRunStftCoverageState,
) -> PostRunStftFrame:
    empty = np.zeros(context.freq_hz.shape, dtype=np.float32)
    axis_frame: AxisFrame = (
        "vehicle" if parse_mount_orientation(sensor_window.mount_orientation) else "sensor_local"
    )
    return PostRunStftFrame(
        run_id=sensor_window.run_id,
        client_id=sensor_window.client_id,
        location=sensor_window.location,
        window_index=sensor_window.window.window_index,
        window_start_t_s=sensor_window.window.start_t_s,
        window_end_t_s=sensor_window.window.end_t_s,
        window_center_t_s=sensor_window.window.center_t_s,
        sample_rate_hz=sensor_window.sample_rate_hz,
        requested_sample_start=sensor_window.requested_sample_start,
        requested_sample_count=sensor_window.requested_sample_count,
        returned_sample_start=sensor_window.returned_sample_start,
        returned_sample_count=sensor_window.returned_sample_count,
        coverage_state=coverage_state,
        data_quality_flags=sensor_window.data_quality_flags,
        mount_orientation=sensor_window.mount_orientation,
        axis_frame=axis_frame,
        gravity_axis=None,
        freq_hz=context.freq_hz.copy(),
        spectrum_by_axis_amp_g={axis: empty.copy() for axis in AXES},
        combined_amp_g=empty.copy(),
        rms_by_axis_g={axis: 0.0 for axis in AXES},
        p2p_by_axis_g={axis: 0.0 for axis in AXES},
    )


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
