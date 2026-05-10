"""Primitive signal metrics used by window-quality scoring."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np

from vibesensor.shared._window_quality_types import (
    WindowClippingAnalysis,
    clamp01,
    normalized_axis_counts,
)
from vibesensor.shared.fft_analysis import broadband_energy_ratio, high_frequency_energy_ratio

_CLIPPING_FULL_SCALE_I16 = 32760
_CLIPPING_EXCLUDED_RATIO = 0.01
_CLIPPING_MIN_REPEATED_RAIL_SAMPLES = 3
_CLIPPING_MIN_FLAT_TOP_RUN = 2
_FLAT_TOP_MIN_PEAK_G = 0.5
_FLAT_TOP_MIN_P2P_G = 0.25
_FLAT_TOP_REL_TOLERANCE = 0.002
_FLAT_TOP_ABS_TOLERANCE_G = 0.02
_CREST_FACTOR_CLEAN = 6.0
_CREST_FACTOR_EXCLUDED = 12.0
_BROADBAND_RATIO_CLEAN = 0.55
_BROADBAND_RATIO_EXCLUDED = 0.82
_MOUNTING_HIGH_FREQUENCY_RATIO_CLEAN = 0.35
_MOUNTING_HIGH_FREQUENCY_RATIO_SUSPECT = 0.70
_MOUNTING_MIN_HIGH_FREQUENCY_HZ = 45.0


@dataclass(frozen=True, slots=True)
class WindowTransientAnalysis:
    score: float
    crest_factor: float | None
    broadband_ratio: float | None


@dataclass(frozen=True, slots=True)
class WindowMountingArtifactAnalysis:
    score: float
    high_frequency_ratio: float | None


def analyze_window_clipping(
    *,
    samples_i16: np.ndarray | None = None,
    samples_g: np.ndarray | None = None,
) -> WindowClippingAnalysis:
    """Detect repeated rail hits and flat-topped waveforms in one sample window."""

    raw_samples = time_axis_samples_any(samples_i16)
    scaled_samples = time_axis_samples_any(samples_g)
    raw_axis_counts = _raw_rail_axis_counts(raw_samples)
    flat_top_axis_counts = _flat_top_axis_counts(scaled_samples)
    axis_counts = (
        max(raw_axis_counts[0], flat_top_axis_counts[0]),
        max(raw_axis_counts[1], flat_top_axis_counts[1]),
        max(raw_axis_counts[2], flat_top_axis_counts[2]),
    )
    total_slots = max(
        int(raw_samples.size) if raw_samples is not None else 0,
        int(scaled_samples.size) if scaled_samples is not None else 0,
    )
    sample_count = sum(axis_counts)
    if sample_count <= 0 or total_slots <= 0:
        return WindowClippingAnalysis(score=1.0, sample_count=0, sample_ratio=0.0)
    sample_ratio = clamp01(float(sample_count) / float(total_slots))
    score = clamp01(1.0 - (sample_ratio / _CLIPPING_EXCLUDED_RATIO))
    return WindowClippingAnalysis(
        score=score,
        sample_count=sample_count,
        sample_ratio=sample_ratio,
        axis_counts=axis_counts,
    )


def analyze_window_transient(samples_g: np.ndarray | None) -> WindowTransientAnalysis:
    if samples_g is None or samples_g.size == 0:
        return WindowTransientAnalysis(score=1.0, crest_factor=None, broadband_ratio=None)
    samples = time_axis_samples(samples_g)
    if samples.size == 0:
        return WindowTransientAnalysis(score=1.0, crest_factor=None, broadband_ratio=None)
    detrended = samples - np.mean(samples, axis=0, keepdims=True)
    magnitude = np.linalg.norm(detrended, axis=1)
    rms = float(np.sqrt(np.mean(np.square(magnitude, dtype=np.float64))))
    if not isfinite(rms) or rms <= 1e-12:
        return WindowTransientAnalysis(score=1.0, crest_factor=None, broadband_ratio=None)
    peak = float(np.max(np.abs(magnitude)))
    crest = peak / rms
    crest_score = _crest_factor_score(crest)
    broadband_ratio = broadband_energy_ratio(detrended.T.astype(np.float32, copy=False))
    broadband_score = _broadband_ratio_score(broadband_ratio)
    return WindowTransientAnalysis(
        score=min(crest_score, broadband_score),
        crest_factor=crest,
        broadband_ratio=broadband_ratio,
    )


def analyze_mounting_artifact(
    samples_g: np.ndarray | None,
    *,
    sample_rate_hz: int | None,
) -> WindowMountingArtifactAnalysis:
    if samples_g is None or sample_rate_hz is None or sample_rate_hz <= 0:
        return WindowMountingArtifactAnalysis(score=1.0, high_frequency_ratio=None)
    samples = time_axis_samples(samples_g)
    if samples.size == 0:
        return WindowMountingArtifactAnalysis(score=1.0, high_frequency_ratio=None)
    detrended = samples - np.mean(samples, axis=0, keepdims=True)
    high_frequency_start_hz = min(
        float(sample_rate_hz) * 0.45,
        max(_MOUNTING_MIN_HIGH_FREQUENCY_HZ, float(sample_rate_hz) * 0.20),
    )
    ratio = high_frequency_energy_ratio(
        detrended.T.astype(np.float32, copy=False),
        sample_rate_hz=sample_rate_hz,
        high_frequency_start_hz=high_frequency_start_hz,
    )
    if ratio is None:
        return WindowMountingArtifactAnalysis(score=1.0, high_frequency_ratio=None)
    return WindowMountingArtifactAnalysis(
        score=_mounting_high_frequency_score(ratio),
        high_frequency_ratio=ratio,
    )


def time_axis_samples(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim != 2:
        return np.empty((0, 3), dtype=np.float32)
    if arr.shape[1] == 3:
        return arr
    if arr.shape[0] == 3:
        return arr.T
    return np.empty((0, 3), dtype=np.float32)


def time_axis_samples_any(samples: np.ndarray | None) -> np.ndarray | None:
    if samples is None:
        return None
    arr = np.asarray(samples)
    if arr.ndim != 2:
        return None
    if arr.shape[1] == 3:
        return arr
    if arr.shape[0] == 3:
        return arr.T
    return None


def _raw_rail_axis_counts(samples: np.ndarray | None) -> tuple[int, int, int]:
    if samples is None or samples.size == 0:
        return (0, 0, 0)
    raw = samples.astype(np.int32, copy=False)
    counts: list[int] = []
    for axis_index in range(3):
        axis = raw[:, axis_index]
        rail_mask = np.abs(axis) >= _CLIPPING_FULL_SCALE_I16
        count = int(np.count_nonzero(rail_mask))
        counts.append(count if count >= _CLIPPING_MIN_REPEATED_RAIL_SAMPLES else 0)
    return normalized_axis_counts(tuple(counts))


def _flat_top_axis_counts(samples: np.ndarray | None) -> tuple[int, int, int]:
    if samples is None or samples.size == 0:
        return (0, 0, 0)
    arr = samples.astype(np.float64, copy=False)
    counts: list[int] = []
    for axis_index in range(3):
        axis_values = arr[:, axis_index]
        finite_axis = axis_values[np.isfinite(axis_values)]
        if finite_axis.size == 0:
            counts.append(0)
            continue
        upper = float(np.max(finite_axis))
        lower = float(np.min(finite_axis))
        peak = max(abs(upper), abs(lower))
        p2p = upper - lower
        if peak < _FLAT_TOP_MIN_PEAK_G or p2p < _FLAT_TOP_MIN_P2P_G:
            counts.append(0)
            continue
        tolerance = max(_FLAT_TOP_ABS_TOLERANCE_G, peak * _FLAT_TOP_REL_TOLERANCE)
        upper_mask = (
            finite_axis >= upper - tolerance
            if upper > 0.0
            else np.zeros_like(
                finite_axis,
                dtype=np.bool_,
            )
        )
        lower_mask = (
            finite_axis <= lower + tolerance
            if lower < 0.0
            else np.zeros_like(
                finite_axis,
                dtype=np.bool_,
            )
        )
        flat_mask = np.logical_or(upper_mask, lower_mask)
        count = int(np.count_nonzero(flat_mask))
        counts.append(count if _longest_true_run(flat_mask) >= _CLIPPING_MIN_FLAT_TOP_RUN else 0)
    return normalized_axis_counts(tuple(counts))


def _longest_true_run(mask: np.ndarray) -> int:
    longest = 0
    current = 0
    for value in mask:
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _mounting_high_frequency_score(ratio: float) -> float:
    if ratio <= _MOUNTING_HIGH_FREQUENCY_RATIO_CLEAN:
        return 1.0
    if ratio >= _MOUNTING_HIGH_FREQUENCY_RATIO_SUSPECT:
        return 0.0
    suspect_range = _MOUNTING_HIGH_FREQUENCY_RATIO_SUSPECT - _MOUNTING_HIGH_FREQUENCY_RATIO_CLEAN
    return clamp01((_MOUNTING_HIGH_FREQUENCY_RATIO_SUSPECT - ratio) / suspect_range)


def _crest_factor_score(crest: float) -> float:
    if crest <= _CREST_FACTOR_CLEAN:
        return 1.0
    if crest >= _CREST_FACTOR_EXCLUDED:
        return 0.0
    transient_range = _CREST_FACTOR_EXCLUDED - _CREST_FACTOR_CLEAN
    return clamp01((_CREST_FACTOR_EXCLUDED - crest) / transient_range)


def _broadband_ratio_score(ratio: float | None) -> float:
    if ratio is None:
        return 1.0
    if ratio <= _BROADBAND_RATIO_CLEAN:
        return 1.0
    if ratio >= _BROADBAND_RATIO_EXCLUDED:
        return 0.0
    transient_range = _BROADBAND_RATIO_EXCLUDED - _BROADBAND_RATIO_CLEAN
    return clamp01((_BROADBAND_RATIO_EXCLUDED - ratio) / transient_range)
