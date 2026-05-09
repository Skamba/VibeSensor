"""Window-level diagnostic features extracted from dense post-run STFT frames."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from vibesensor.shared.fft_analysis import AXES, Axis, BoolArray, FloatArray
from vibesensor.shared.sensor_orientation import AxisFrame, SignedAxis
from vibesensor.use_cases.diagnostics.post_run_raw_windows import (
    PostRunRawWindowDataQualityFlag,
)
from vibesensor.use_cases.diagnostics.post_run_stft import (
    PostRunDenseStftResult,
    PostRunStftCoverageState,
    PostRunStftFrame,
)
from vibesensor.vibration_strength import (
    StrengthPeak,
    VibrationStrengthMetrics,
    compute_vibration_strength_db,
    empty_vibration_strength_metrics,
)

type PostRunWindowFeatureQualityFlag = (
    PostRunRawWindowDataQualityFlag
    | Literal[
        "empty_spectrum",
        "frequency_mask_empty",
        "invalid_spectrum_values",
        "no_dominant_peak",
        "sensor_orientation_unknown",
    ]
)


@dataclass(frozen=True, slots=True)
class PostRunWindowFeatureConfig:
    """Configuration for reducing STFT frames into per-window features."""

    feature_min_hz: float | None = None
    feature_max_hz: float | None = None
    excluded_frequency_ranges_hz: tuple[tuple[float, float], ...] = ()
    top_peak_count: int = 8


@dataclass(frozen=True, slots=True)
class PostRunWindowAxisDominance:
    """Dominant-axis evidence at the selected feature peak."""

    axis: Axis | None
    axis_frame: AxisFrame
    axis_amp_g: float
    combined_amp_g: float
    ratio: float | None


@dataclass(frozen=True, slots=True)
class PostRunWindowFeature:
    """Per-window, per-sensor diagnostic feature output."""

    run_id: str
    client_id: str
    location: str
    window_index: int
    window_start_t_s: float
    window_end_t_s: float
    window_center_t_s: float
    sample_rate_hz: int
    coverage_state: PostRunStftCoverageState
    data_quality_flags: tuple[PostRunRawWindowDataQualityFlag, ...]
    feature_quality_flags: tuple[PostRunWindowFeatureQualityFlag, ...]
    mount_orientation: str | None
    axis_frame: AxisFrame
    gravity_axis: SignedAxis | None
    dominant_freq_hz: float | None
    vibration_strength_db: float | None
    peak_amp_g: float | None
    noise_floor_amp_g: float | None
    strength_bucket: str | None
    top_peaks: tuple[StrengthPeak, ...]
    axis_dominance: PostRunWindowAxisDominance
    rms_by_axis_g: dict[Axis, float]
    p2p_by_axis_g: dict[Axis, float]
    max_axis_rms_g: float
    max_axis_p2p_g: float


@dataclass(frozen=True, slots=True)
class PostRunWindowFeatureResult:
    """In-memory feature extraction result for dense post-run frames."""

    config: PostRunWindowFeatureConfig
    features: tuple[PostRunWindowFeature, ...]

    def features_for_sensor(self, client_id: str) -> tuple[PostRunWindowFeature, ...]:
        return tuple(feature for feature in self.features if feature.client_id == client_id)


def extract_post_run_window_features(
    stft: PostRunDenseStftResult | Iterable[PostRunStftFrame],
    *,
    config: PostRunWindowFeatureConfig | None = None,
) -> PostRunWindowFeatureResult:
    """Extract deterministic diagnostic features from dense STFT frames."""

    effective_config = config or PostRunWindowFeatureConfig()
    _validate_config(effective_config)
    frames = stft.frames if isinstance(stft, PostRunDenseStftResult) else tuple(stft)
    return PostRunWindowFeatureResult(
        config=effective_config,
        features=tuple(_feature_from_frame(frame, config=effective_config) for frame in frames),
    )


def post_run_window_feature_debug_rows(
    features: Iterable[PostRunWindowFeature],
) -> tuple[dict[str, object], ...]:
    """Return compact debug rows for synthetic runs and later pipeline work."""

    rows: list[dict[str, object]] = []
    for feature in features:
        rows.append(
            {
                "run_id": feature.run_id,
                "client_id": feature.client_id,
                "location": feature.location,
                "window_index": feature.window_index,
                "window_center_t_s": feature.window_center_t_s,
                "dominant_freq_hz": feature.dominant_freq_hz,
                "vibration_strength_db": feature.vibration_strength_db,
                "strength_bucket": feature.strength_bucket,
                "axis": feature.axis_dominance.axis,
                "axis_frame": feature.axis_frame,
                "gravity_axis": feature.gravity_axis,
                "coverage_state": feature.coverage_state,
                "quality_flags": list(feature.feature_quality_flags),
            }
        )
    return tuple(rows)


def _validate_config(config: PostRunWindowFeatureConfig) -> None:
    if config.feature_min_hz is not None and config.feature_min_hz < 0:
        raise ValueError("post-run window features require feature_min_hz >= 0")
    if config.feature_max_hz is not None and config.feature_max_hz < 0:
        raise ValueError("post-run window features require feature_max_hz >= 0")
    if (
        config.feature_min_hz is not None
        and config.feature_max_hz is not None
        and config.feature_max_hz < config.feature_min_hz
    ):
        raise ValueError("post-run window features require feature_max_hz >= feature_min_hz")
    if config.top_peak_count <= 0:
        raise ValueError("post-run window features require top_peak_count > 0")
    for start_hz, end_hz in config.excluded_frequency_ranges_hz:
        if start_hz < 0 or end_hz < 0 or end_hz < start_hz:
            raise ValueError("excluded frequency ranges must be non-negative and ordered")


def _feature_from_frame(
    frame: PostRunStftFrame,
    *,
    config: PostRunWindowFeatureConfig,
) -> PostRunWindowFeature:
    freq_hz, combined_amp, axis_spectra, quality_flags = _sanitized_aligned_spectra(frame)
    frequency_mask = _feature_frequency_mask(freq_hz, config=config)
    if freq_hz.size == 0 or combined_amp.size == 0:
        _append_unique_flag(quality_flags, "empty_spectrum")
    if not np.any(frequency_mask):
        _append_unique_flag(quality_flags, "frequency_mask_empty")
    masked_freq = freq_hz[frequency_mask]
    masked_combined = combined_amp[frequency_mask]
    masked_axis_spectra = {axis: values[frequency_mask] for axis, values in axis_spectra.items()}
    strength_metrics = _strength_metrics(
        freq_hz=masked_freq,
        combined_amp_g=masked_combined,
        top_peak_count=config.top_peak_count,
    )
    top_peaks = tuple(
        peak for peak in strength_metrics["top_peaks"] if peak["hz"] > 0 and peak["amp"] > 0
    )
    if not top_peaks:
        _append_unique_flag(quality_flags, "no_dominant_peak")
    dominant_freq_hz = top_peaks[0]["hz"] if top_peaks else None
    if frame.axis_frame != "vehicle":
        _append_unique_flag(quality_flags, "sensor_orientation_unknown")
    axis_dominance = _axis_dominance(
        freq_hz=masked_freq,
        axis_spectra=masked_axis_spectra,
        combined_amp_g=masked_combined,
        dominant_freq_hz=dominant_freq_hz,
        axis_frame=frame.axis_frame,
    )
    rms_by_axis = _axis_float_map(frame.rms_by_axis_g)
    p2p_by_axis = _axis_float_map(frame.p2p_by_axis_g)
    return PostRunWindowFeature(
        run_id=frame.run_id,
        client_id=frame.client_id,
        location=frame.location,
        window_index=frame.window_index,
        window_start_t_s=frame.window_start_t_s,
        window_end_t_s=frame.window_end_t_s,
        window_center_t_s=frame.window_center_t_s,
        sample_rate_hz=frame.sample_rate_hz,
        coverage_state=frame.coverage_state,
        data_quality_flags=frame.data_quality_flags,
        feature_quality_flags=tuple(quality_flags),
        mount_orientation=frame.mount_orientation,
        axis_frame=frame.axis_frame,
        gravity_axis=frame.gravity_axis,
        dominant_freq_hz=dominant_freq_hz,
        vibration_strength_db=_positive_peak_metric(
            strength_metrics,
            "vibration_strength_db",
            has_peak=bool(top_peaks),
        ),
        peak_amp_g=_positive_peak_metric(strength_metrics, "peak_amp_g", has_peak=bool(top_peaks)),
        noise_floor_amp_g=float(strength_metrics["noise_floor_amp_g"]),
        strength_bucket=strength_metrics["strength_bucket"],
        top_peaks=top_peaks,
        axis_dominance=axis_dominance,
        rms_by_axis_g=rms_by_axis,
        p2p_by_axis_g=p2p_by_axis,
        max_axis_rms_g=max(rms_by_axis.values(), default=0.0),
        max_axis_p2p_g=max(p2p_by_axis.values(), default=0.0),
    )


def _sanitized_aligned_spectra(
    frame: PostRunStftFrame,
) -> tuple[
    FloatArray,
    FloatArray,
    dict[Axis, FloatArray],
    list[PostRunWindowFeatureQualityFlag],
]:
    quality_flags: list[PostRunWindowFeatureQualityFlag] = list(frame.data_quality_flags)
    freq_hz = np.asarray(frame.freq_hz, dtype=np.float32)
    combined_amp = np.asarray(frame.combined_amp_g, dtype=np.float32)
    axis_spectra = {
        axis: np.asarray(frame.spectrum_by_axis_amp_g.get(axis, np.empty(0)), dtype=np.float32)
        for axis in AXES
    }
    target_len = min(
        [freq_hz.size, combined_amp.size, *(values.size for values in axis_spectra.values())],
        default=0,
    )
    freq_hz = freq_hz[:target_len]
    combined_amp = combined_amp[:target_len]
    axis_spectra = {axis: values[:target_len] for axis, values in axis_spectra.items()}
    invalid = (
        not np.all(np.isfinite(freq_hz))
        or not np.all(np.isfinite(combined_amp))
        or any(not np.all(np.isfinite(values)) for values in axis_spectra.values())
    )
    if invalid:
        _append_unique_flag(quality_flags, "invalid_spectrum_values")
    return (
        np.nan_to_num(freq_hz, copy=True, nan=0.0, posinf=0.0, neginf=0.0),
        _clean_amp_array(combined_amp),
        {axis: _clean_amp_array(values) for axis, values in axis_spectra.items()},
        quality_flags,
    )


def _feature_frequency_mask(
    freq_hz: FloatArray,
    *,
    config: PostRunWindowFeatureConfig,
) -> BoolArray:
    mask = np.ones(freq_hz.shape, dtype=np.bool_)
    if config.feature_min_hz is not None:
        mask &= freq_hz >= np.float32(config.feature_min_hz)
    if config.feature_max_hz is not None:
        mask &= freq_hz <= np.float32(config.feature_max_hz)
    for start_hz, end_hz in config.excluded_frequency_ranges_hz:
        mask &= ~((freq_hz >= np.float32(start_hz)) & (freq_hz <= np.float32(end_hz)))
    return mask


def _strength_metrics(
    *,
    freq_hz: FloatArray,
    combined_amp_g: FloatArray,
    top_peak_count: int,
) -> VibrationStrengthMetrics:
    if freq_hz.size == 0 or combined_amp_g.size == 0:
        return empty_vibration_strength_metrics()
    return compute_vibration_strength_db(
        freq_hz=freq_hz,
        combined_spectrum_amp_g_values=combined_amp_g,
        top_n=top_peak_count,
    )


def _axis_dominance(
    *,
    freq_hz: FloatArray,
    axis_spectra: dict[Axis, FloatArray],
    combined_amp_g: FloatArray,
    dominant_freq_hz: float | None,
    axis_frame: AxisFrame,
) -> PostRunWindowAxisDominance:
    if axis_frame != "vehicle" or dominant_freq_hz is None or freq_hz.size == 0:
        return PostRunWindowAxisDominance(
            axis=None,
            axis_frame=axis_frame,
            axis_amp_g=0.0,
            combined_amp_g=0.0,
            ratio=None,
        )
    peak_idx = int(np.argmin(np.abs(freq_hz - np.float32(dominant_freq_hz))))
    axis_amps = {axis: float(axis_spectra[axis][peak_idx]) for axis in AXES}
    dominant_axis, dominant_amp = max(axis_amps.items(), key=lambda item: item[1])
    combined_amp = float(combined_amp_g[peak_idx]) if peak_idx < combined_amp_g.size else 0.0
    ratio = dominant_amp / combined_amp if combined_amp > 0.0 else None
    return PostRunWindowAxisDominance(
        axis=dominant_axis if dominant_amp > 0.0 else None,
        axis_frame=axis_frame,
        axis_amp_g=dominant_amp,
        combined_amp_g=combined_amp,
        ratio=ratio,
    )


def _axis_float_map(values: dict[Axis, float]) -> dict[Axis, float]:
    return {axis: _finite_non_negative(values.get(axis, 0.0)) for axis in AXES}


def _clean_amp_array(values: FloatArray) -> FloatArray:
    return (
        np.nan_to_num(
            values,
            copy=True,
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        .astype(np.float32, copy=False)
        .clip(min=0.0)
    )


def _finite_non_negative(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    value_float = float(value)
    if not np.isfinite(value_float):
        return 0.0
    return max(0.0, value_float)


def _positive_peak_metric(
    metrics: VibrationStrengthMetrics,
    key: Literal["vibration_strength_db", "peak_amp_g"],
    *,
    has_peak: bool,
) -> float | None:
    if not has_peak:
        return None
    return float(metrics[key])


def _append_unique_flag(
    flags: list[PostRunWindowFeatureQualityFlag],
    flag: PostRunWindowFeatureQualityFlag,
) -> None:
    if flag not in flags:
        flags.append(flag)
