"""Vibration-strength computation — canonical implementation.

This module is the single source of truth for all vibration-strength
arithmetic used by VibeSensor.

Hot-path functions (`combined_spectrum_amp_g`, `compute_vibration_strength_db`,
`noise_floor_amp_p20_g`) accept both plain Python lists and numpy arrays.
Scalar functions (`vibration_strength_db_scalar`, `bucket_for_strength`) remain
pure Python.

Key functions
-------------
vibration_strength_db_scalar
    Core dB formula: ``20*log10((peak+eps)/(floor+eps))``.
compute_vibration_strength_db
    Full pipeline: spectrum → peak detection → floor estimation → dB result.
combined_spectrum_amp_g
    Canonical multi-axis combination: ``sqrt(mean(axis_amp²))``.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite, log10
from statistics import median as _stdlib_median
from typing import Final, NotRequired, TypedDict, cast

import numpy as np
import numpy.typing as npt

from vibesensor.dsp.strength_bands import _buckets_for_strength_db_aligned, bucket_for_strength

__all__ = [
    "CALIBRATION_PROFILE_ID",
    "compute_db",
    "compute_db_or_none",
    "empty_vibration_strength_metrics",
    "PEAK_BANDWIDTH_HZ",
    "PEAK_DETECTOR_VERSION",
    "PEAK_SEPARATION_HZ",
    "LOCAL_FLOOR_HALF_WIDTH_HZ",
    "PEAK_THRESHOLD_FLOOR_RATIO",
    "StrengthPeak",
    "STRENGTH_ALGORITHM_VERSION",
    "STRENGTH_EPSILON_FLOOR_RATIO",
    "STRENGTH_EPSILON_MIN_G",
    "combined_spectrum_amp_g",
    "compute_vibration_strength_db",
    "median",
    "noise_floor_amp_p20_g",
    "peak_band_rms_amp_g",
    "percentile",
    "strength_floor_amp_g",
    "VibrationStrengthMetrics",
    "vibration_strength_db_scalar",
]

PEAK_BANDWIDTH_HZ: Final[float] = 1.2
PEAK_SEPARATION_HZ: Final[float] = 1.2
STRENGTH_EPSILON_MIN_G: Final[float] = 1e-9
STRENGTH_EPSILON_FLOOR_RATIO: Final[float] = 0.05
PEAK_THRESHOLD_FLOOR_RATIO: Final[float] = 2.6
LOCAL_FLOOR_HALF_WIDTH_HZ: Final[float] = 5.0
STRENGTH_ALGORITHM_VERSION: Final[str] = "strength-db-scalar-v1"
PEAK_DETECTOR_VERSION: Final[str] = "peak-band-rms-v1"
CALIBRATION_PROFILE_ID: Final[str] = "noise-floor-p20-v1"

ArrayLike = Sequence[float] | npt.NDArray[np.floating]


class StrengthPeak(TypedDict):
    hz: float
    amp: float
    vibration_strength_db: float
    strength_bucket: str | None
    # What the peak stands out from where it sits (``_peak_local_floors``). The
    # analysis reads it from recorded peaks; the live page does not need it.
    local_floor_amp_g: NotRequired[float]


class VibrationStrengthMetrics(TypedDict):
    vibration_strength_db: float
    peak_amp_g: float
    noise_floor_amp_g: float
    strength_bucket: str | None
    top_peaks: list[StrengthPeak]


def empty_vibration_strength_metrics() -> VibrationStrengthMetrics:
    return {
        "vibration_strength_db": 0.0,
        "peak_amp_g": 0.0,
        "noise_floor_amp_g": 0.0,
        "strength_bucket": None,
        "top_peaks": [],
    }


def median(values: list[float]) -> float:
    """Return the median of *values*, or 0.0 for an empty list."""
    if not values:
        return 0.0
    return float(_stdlib_median(values))


def percentile(sorted_values: list[float], q: float) -> float:
    """Return the *q*-th percentile (0–1) of *sorted_values* via linear interpolation."""
    if not sorted_values:
        return 0.0
    return float(np.quantile(sorted_values, max(0.0, min(1.0, float(q)))))


def _aligned_float_arrays(
    left: ArrayLike,
    right: ArrayLike,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    left_arr = np.asarray(left, dtype=np.float64)
    right_arr = np.asarray(right, dtype=np.float64)
    n = min(left_arr.size, right_arr.size)
    return left_arr[:n], right_arr[:n]


def _quantile_or_zero(values: npt.NDArray[np.float64], q: float) -> float:
    if values.size == 0:
        return 0.0
    q_value = float(q)
    if not 0.0 <= q_value <= 1.0:
        return float(np.quantile(values, q_value))
    if values.size == 1:
        return float(values[0])
    if q_value == 0.0:
        return float(np.min(values))
    if q_value == 1.0:
        return float(np.max(values))

    # The linear-interpolation quantile only needs the two bracketing order
    # statistics, so use partition instead of the heavier generic quantile path.
    position = q_value * float(values.size - 1)
    lower_idx = int(position)
    upper_idx = int(np.ceil(position))
    if lower_idx == upper_idx:
        partitioned = np.partition(values, lower_idx)
        return float(partitioned[lower_idx])

    partitioned = np.partition(values, (lower_idx, upper_idx))
    lower_value = float(partitioned[lower_idx])
    upper_value = float(partitioned[upper_idx])
    return lower_value + (upper_value - lower_value) * (position - lower_idx)


def _median_or_zero(values: npt.NDArray[np.float64]) -> float:
    if values.size == 0:
        return 0.0
    mid = values.size // 2
    if values.size % 2:
        partitioned = np.partition(values, mid)
        return float(partitioned[mid])

    partitioned = np.partition(values, (mid - 1, mid))
    return float((partitioned[mid - 1] + partitioned[mid]) * 0.5)


def _combined_spectrum_amp_g_array(
    *,
    axis_spectra_amp_g: Sequence[ArrayLike] | npt.NDArray[np.floating],
    axis_count_for_mean: int | None = None,
) -> npt.NDArray[np.float64]:
    if isinstance(axis_spectra_amp_g, np.ndarray):
        if axis_spectra_amp_g.size == 0:
            return np.empty(0, dtype=np.float64)
        arr = np.asarray(axis_spectra_amp_g, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
    else:
        if not axis_spectra_amp_g:
            return np.empty(0, dtype=np.float64)
        target_len = min((len(a) for a in axis_spectra_amp_g), default=0)
        if target_len <= 0:
            return np.empty(0, dtype=np.float64)
        arr = np.empty((len(axis_spectra_amp_g), target_len), dtype=np.float64)
        for i, a in enumerate(axis_spectra_amp_g):
            arr[i] = np.asarray(a, dtype=np.float64)[:target_len]

    arr = np.where(np.isfinite(arr), arr, 0.0)
    divisor = (
        max(1.0, float(axis_count_for_mean))
        if axis_count_for_mean is not None
        else max(1.0, float(arr.shape[0]))
    )
    result: npt.NDArray[np.float64] = np.sqrt(np.sum(arr**2, axis=0) / divisor)
    return result


def combined_spectrum_amp_g(
    *,
    axis_spectra_amp_g: Sequence[ArrayLike] | npt.NDArray[np.floating],
    axis_count_for_mean: int | None = None,
) -> list[float]:
    """Canonical combined spectrum amplitude definition.

    Input axis arrays must be single-sided FFT amplitude magnitudes in g.
    Output is ``sqrt(mean(axis_amp^2))`` per frequency bin — e.g.
    ``sqrt((x^2 + y^2 + z^2) / 3)`` when three axes are provided.

    Accepts plain Python lists or numpy arrays.

    Parameters
    ----------
    axis_spectra_amp_g:
        List of per-axis amplitude arrays.  All arrays are truncated to the
        shortest length before combining.
    axis_count_for_mean:
        Denominator used for the mean.  When ``None`` (default) the actual
        number of input axes is used.  Pass an explicit value to keep the
        denominator fixed (e.g. always divide by 3 even when only 2 axes are
        valid), which preserves comparability across partial-axis frames.
    """
    result = _combined_spectrum_amp_g_array(
        axis_spectra_amp_g=axis_spectra_amp_g,
        axis_count_for_mean=axis_count_for_mean,
    )
    return cast(list[float], result.tolist())


# Public helper APIs accept ArrayLike for callers and tests. Once
# compute_vibration_strength_db() normalizes its inputs, the hot path should stay
# on the private ndarray-only helpers below.
def noise_floor_amp_p20_g(*, combined_spectrum_amp_g: ArrayLike) -> float:
    """Return the P20 amplitude floor in g, skipping the DC bin (index 0).

    Returns ``0.0`` when the spectrum is empty or contains only the DC bin,
    because the DC component (index 0, 0 Hz) carries gravitational acceleration
    (~1 g on a level surface) rather than vibration noise, and using it as the
    noise floor would raise the floor by orders of magnitude and suppress all
    real vibration findings.
    """
    band = np.asarray(combined_spectrum_amp_g, dtype=np.float64)
    band = np.where(np.isfinite(band), np.maximum(band, 0.0), 0.0)
    return _noise_floor_amp_p20_g_aligned(combined_spectrum_amp_g=band)


def _spectrum_includes_dc_bin_aligned(*, freq_hz: npt.NDArray[np.float64] | None) -> bool:
    if freq_hz is None or freq_hz.size == 0:
        return True
    first_hz = float(freq_hz[0])
    return isfinite(first_hz) and abs(first_hz) <= 1e-12


def _noise_floor_amp_p20_g_aligned(
    *,
    combined_spectrum_amp_g: npt.NDArray[np.float64],
    freq_hz: npt.NDArray[np.float64] | None = None,
) -> float:
    band = combined_spectrum_amp_g
    noise_bins = band[1:] if _spectrum_includes_dc_bin_aligned(freq_hz=freq_hz) else band
    if noise_bins.size == 0:
        # Empty spectrum, DC-only, or DC removed before slicing: no usable
        # frequency content remains to estimate the noise floor from.
        return 0.0
    return _quantile_or_zero(noise_bins, 0.20)


def strength_floor_amp_g(
    *,
    freq_hz: ArrayLike,
    combined_spectrum_amp_g: ArrayLike,
    peak_indexes: list[int],
    exclusion_hz: float,
    min_hz: float,
    max_hz: float,
) -> float:
    """Estimate the strength floor as the median amplitude in non-peak bins.

    Bins within *exclusion_hz* of any detected peak are excluded.
    Falls back to :func:`noise_floor_amp_p20_g` when all bins are excluded.
    """
    freq, amps = _aligned_float_arrays(freq_hz, combined_spectrum_amp_g)
    clean_amps = np.where(np.isfinite(amps), np.maximum(amps, 0.0), 0.0)
    return _strength_floor_amp_g_aligned(
        freq_hz=freq,
        combined_spectrum_amp_g=clean_amps,
        peak_indexes=peak_indexes,
        exclusion_hz=exclusion_hz,
        in_range_mask=(freq >= min_hz) & (freq <= max_hz),
    )


def _strength_floor_amp_g_aligned(
    *,
    freq_hz: npt.NDArray[np.float64],
    combined_spectrum_amp_g: npt.NDArray[np.float64],
    peak_indexes: list[int],
    exclusion_hz: float,
    in_range_mask: npt.NDArray[np.bool_] | None = None,
) -> float:
    if freq_hz.size == 0:
        return 0.0
    base_mask = _range_mask_aligned(freq_hz, in_range_mask)
    return _floor_from_bins_aligned(
        amps=combined_spectrum_amp_g,
        base_mask=base_mask,
        floor_bins=_floor_bins_mask_aligned(
            freq_hz=freq_hz,
            base_mask=base_mask,
            peak_indexes=peak_indexes,
            exclusion_hz=exclusion_hz,
        ),
    )


def _floor_from_bins_aligned(
    *,
    amps: npt.NDArray[np.float64],
    base_mask: npt.NDArray[np.bool_],
    floor_bins: npt.NDArray[np.bool_],
) -> float:
    selected = amps[floor_bins]
    if selected.size == 0:
        # All bins were within peak exclusion zones.  Compute P20 of all
        # qualifying in-range bins instead of delegating to
        # noise_floor_amp_p20_g, which unconditionally skips index 0
        # (assuming DC content at 0 Hz) — an assumption that breaks when
        # the caller has already stripped the DC bin from the spectrum.
        return _quantile_or_zero(amps[base_mask], 0.20)
    return _median_or_zero(selected)


def _range_mask_aligned(
    freq_hz: npt.NDArray[np.float64], in_range_mask: npt.NDArray[np.bool_] | None
) -> npt.NDArray[np.bool_]:
    if in_range_mask is None:
        return np.ones(freq_hz.shape, dtype=np.bool_)
    if in_range_mask.shape != freq_hz.shape:
        raise ValueError(
            "strength floor range mask shape does not match aligned spectrum size "
            f"{in_range_mask.shape} != {freq_hz.shape}"
        )
    return in_range_mask


def _floor_bins_mask_aligned(
    *,
    freq_hz: npt.NDArray[np.float64],
    base_mask: npt.NDArray[np.bool_],
    peak_indexes: list[int],
    exclusion_hz: float,
) -> npt.NDArray[np.bool_]:
    """The in-range bins outside *exclusion_hz* of every peak: the floor's bins."""
    selected_mask = base_mask.copy()
    peak_idx = [idx for idx in peak_indexes if 0 <= idx < freq_hz.size]
    if peak_idx:
        _exclude_peak_regions_aligned(
            selected_mask=selected_mask,
            freq_hz=freq_hz,
            peak_indexes=peak_idx,
            exclusion_hz=exclusion_hz,
        )
    return selected_mask


def _window_medians(
    values: npt.NDArray[np.float64],
    index: npt.NDArray[np.intp],
    counted: npt.NDArray[np.bool_],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.intp]]:
    """Per row, the median of ``values[index]`` over the *counted* entries, and their count."""
    ordered = np.sort(np.where(counted, values[index], np.inf), axis=1)
    counts = counted.sum(axis=1)
    rows = np.arange(index.shape[0])
    lower = ordered[rows, np.maximum(counts - 1, 0) // 2]
    upper = ordered[rows, np.minimum(counts // 2, index.shape[1] - 1)]
    return 0.5 * (lower + upper), counts


def _peak_local_floors(
    *,
    freq_hz: npt.NDArray[np.float64],
    combined_spectrum_amp_g: npt.NDArray[np.float64],
    floor_bins: npt.NDArray[np.bool_],
    center_indexes: list[int],
) -> npt.NDArray[np.float64]:
    """What each peak stands out from where it sits: its local floor.

    The median of the floor bins within ``LOCAL_FLOOR_HALF_WIDTH_HZ`` of the
    peak. Where peaks crowd that whole neighbourhood (no floor bin left), the
    median of every bin there: a peak among many is as strong as its crowd.
    """
    if not center_indexes:
        return np.empty(0, dtype=np.float64)
    bin_hz = float(freq_hz[1] - freq_hz[0]) if freq_hz.size > 1 else 0.0
    half_bins = int(round(LOCAL_FLOOR_HALF_WIDTH_HZ / bin_hz)) if bin_hz > 0 else 0
    centres = np.asarray(center_indexes, dtype=np.intp)
    index = centres[:, None] + np.arange(-half_bins, half_bins + 1, dtype=np.intp)[None, :]
    inside = (index >= 0) & (index < freq_hz.size)
    index = np.clip(index, 0, freq_hz.size - 1)
    floors, floor_counts = _window_medians(
        combined_spectrum_amp_g, index, inside & floor_bins[index]
    )
    crowded = floor_counts == 0
    if crowded.any():
        crowd_medians, _counts = _window_medians(
            combined_spectrum_amp_g, index[crowded], inside[crowded]
        )
        floors[crowded] = crowd_medians
    return floors


def _exclude_peak_regions_aligned(
    *,
    selected_mask: npt.NDArray[np.bool_],
    freq_hz: npt.NDArray[np.float64],
    peak_indexes: list[int],
    exclusion_hz: float,
) -> None:
    peak_ranges = _peak_band_index_ranges_aligned(
        freq_hz=freq_hz,
        center_indexes=peak_indexes,
        bandwidth_hz=exclusion_hz,
    )
    if peak_ranges is None:
        peak_hz = freq_hz[np.asarray(peak_indexes, dtype=np.intp)]
        if peak_hz.size:
            selected_mask &= ~_peak_exclusion_mask_broadcast_aligned(
                freq_hz=freq_hz,
                peak_hz=peak_hz,
                exclusion_hz=exclusion_hz,
            )
        return
    left_bounds, right_bounds = peak_ranges
    for start_idx, stop_idx in zip(
        left_bounds.tolist(),
        right_bounds.tolist(),
        strict=True,
    ):
        selected_mask[start_idx:stop_idx] = False


def _peak_exclusion_mask_broadcast_aligned(
    *,
    freq_hz: npt.NDArray[np.float64],
    peak_hz: npt.NDArray[np.float64],
    exclusion_hz: float,
) -> npt.NDArray[np.bool_]:
    return cast(
        npt.NDArray[np.bool_],
        np.count_nonzero(
            np.abs(freq_hz[:, None] - peak_hz[None, :]) <= exclusion_hz,
            axis=1,
        )
        > 0,
    )


def peak_band_rms_amp_g(
    *,
    freq_hz: ArrayLike,
    combined_spectrum_amp_g: ArrayLike,
    center_idx: int,
    bandwidth_hz: float,
) -> float:
    """Return the RMS amplitude in g of bins within *bandwidth_hz* of *center_idx*.

    Raises ``ValueError`` when *center_idx* is outside the aligned spectrum.
    """
    freq, amps = _aligned_float_arrays(freq_hz, combined_spectrum_amp_g)
    return _peak_band_rms_amp_g_aligned(
        freq_hz=freq,
        combined_spectrum_amp_g=amps,
        center_idx=center_idx,
        bandwidth_hz=bandwidth_hz,
    )


def _peak_band_rms_amp_g_aligned(
    *,
    freq_hz: npt.NDArray[np.float64],
    combined_spectrum_amp_g: npt.NDArray[np.float64],
    center_idx: int,
    bandwidth_hz: float,
) -> float:
    freq = freq_hz
    amps = combined_spectrum_amp_g
    if not (0 <= center_idx < freq.size):
        raise ValueError(
            f"center_idx {center_idx} out of range for aligned spectrum size {freq.size}"
        )
    center_hz = float(freq[center_idx])
    band = amps[np.abs(freq - center_hz) <= bandwidth_hz]
    if band.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(band, dtype=np.float64))))


def _peak_band_index_ranges_aligned(
    *,
    freq_hz: npt.NDArray[np.float64],
    center_indexes: list[int],
    bandwidth_hz: float,
) -> tuple[npt.NDArray[np.intp], npt.NDArray[np.intp]] | None:
    if not center_indexes:
        empty = np.empty(0, dtype=np.intp)
        return empty, empty
    if np.any(freq_hz[1:] < freq_hz[:-1]):
        return None
    center_idx_array = np.asarray(center_indexes, dtype=np.intp)
    center_hz = freq_hz[center_idx_array]
    left_bounds = np.searchsorted(freq_hz, center_hz - bandwidth_hz, side="left")
    right_bounds = np.searchsorted(freq_hz, center_hz + bandwidth_hz, side="right")
    return left_bounds, right_bounds


def _peak_band_rms_amp_g_from_ranges(
    *,
    combined_spectrum_amp_g: npt.NDArray[np.float64],
    left_bounds: npt.NDArray[np.intp],
    right_bounds: npt.NDArray[np.intp],
) -> npt.NDArray[np.float64]:
    if left_bounds.size == 0:
        return np.empty(0, dtype=np.float64)
    squared = np.square(combined_spectrum_amp_g, dtype=np.float64)
    prefix_sum = np.empty(squared.size + 1, dtype=np.float64)
    prefix_sum[0] = 0.0
    np.cumsum(squared, out=prefix_sum[1:])

    counts = right_bounds - left_bounds
    result = np.zeros(left_bounds.shape, dtype=np.float64)
    valid = counts > 0
    if np.any(valid):
        sums = prefix_sum[right_bounds[valid]] - prefix_sum[left_bounds[valid]]
        result[valid] = np.sqrt(sums / counts[valid])
    return result


def _local_maxima(values: npt.NDArray[np.float64]) -> npt.NDArray[np.intp]:
    """Indexes of interior local maxima, ascending (``scipy.signal.find_peaks`` rules).

    A peak rises strictly from its left neighbour and falls strictly to its
    right one; a flat top counts once, at its middle (rounded down). The first
    and last samples are never peaks. Implemented in numpy because importing
    ``scipy.signal`` costs seconds on the Pi at server start.
    """

    if values.size < 3:
        return np.empty(0, dtype=np.intp)
    left = values[:-1]
    right = values[1:]
    if not np.any(left == right):
        # No flat tops (the usual spectrum): a peak is above both neighbours.
        return np.flatnonzero((right[:-1] > left[:-1]) & (left[1:] > right[1:])) + 1
    # Collapse runs of equal values; a peak is a run higher than both neighbours.
    run_starts = np.flatnonzero(np.concatenate(([True], right != left)))
    run_ends = np.append(run_starts[1:] - 1, values.size - 1)
    run_values = values[run_starts]
    is_peak = (run_values[1:-1] > run_values[:-2]) & (run_values[1:-1] > run_values[2:])
    return np.asarray((run_starts[1:-1][is_peak] + run_ends[1:-1][is_peak]) // 2, dtype=np.intp)


def _candidate_peak_indexes(
    values: npt.NDArray[np.float64], threshold: float, limit: int
) -> list[int]:
    """The *limit* highest local maxima at or above *threshold*, highest first."""
    peak_indexes = _local_maxima(values)
    peak_indexes = peak_indexes[values[peak_indexes] >= threshold]
    if values.size > 1:
        last_idx = values.size - 1
        last_val = float(values[last_idx])
        if last_val >= threshold and last_val > float(values[last_idx - 1]):
            peak_indexes = np.append(peak_indexes, last_idx)
    if peak_indexes.size == 0:
        return []
    order = np.argsort(values[peak_indexes])[::-1]
    return cast(list[int], peak_indexes[order[:limit]].tolist())


def vibration_strength_db_scalar(
    *,
    peak_band_rms_amp_g: float,
    floor_amp_g: float,
    epsilon_g: float | None = None,
) -> float:
    """Compute vibration strength in dB: ``20*log10((peak+eps)/(floor+eps))``.

    *epsilon_g* defaults to ``max(1e-9, floor * 0.05)`` to avoid log(0)
    and to set a meaningful dynamic range floor. Non-finite or negative inputs
    are clamped to ``0.0`` before epsilon is applied.
    """
    _floor_raw = float(floor_amp_g)
    _band_raw = float(peak_band_rms_amp_g)
    floor = max(0.0, _floor_raw) if isfinite(_floor_raw) else 0.0
    band = max(0.0, _band_raw) if isfinite(_band_raw) else 0.0
    eps = (
        max(STRENGTH_EPSILON_MIN_G, floor * STRENGTH_EPSILON_FLOOR_RATIO)
        if epsilon_g is None
        else max(STRENGTH_EPSILON_MIN_G, float(epsilon_g))
    )
    return 20.0 * log10((band + eps) / (floor + eps))


def _batch_vibration_strength_db_aligned(
    *,
    peak_band_rms_amp_g_values: npt.NDArray[np.float64],
    floor_amp_g: float,
    epsilon_g: float | None = None,
) -> npt.NDArray[np.float64]:
    floor_raw = float(floor_amp_g)
    floor = max(0.0, floor_raw) if isfinite(floor_raw) else 0.0
    eps = (
        max(STRENGTH_EPSILON_MIN_G, floor * STRENGTH_EPSILON_FLOOR_RATIO)
        if epsilon_g is None
        else max(STRENGTH_EPSILON_MIN_G, float(epsilon_g))
    )
    band = np.where(
        np.isfinite(peak_band_rms_amp_g_values),
        np.maximum(peak_band_rms_amp_g_values, 0.0),
        0.0,
    )
    return 20.0 * np.log10((band + eps) / (floor + eps))


def compute_vibration_strength_db(
    *,
    freq_hz: ArrayLike,
    combined_spectrum_amp_g_values: ArrayLike,
    peak_bandwidth_hz: float = PEAK_BANDWIDTH_HZ,
    peak_separation_hz: float = PEAK_SEPARATION_HZ,
    top_n: int = 5,
    strength_range_mask: npt.NDArray[np.bool_] | None = None,
) -> VibrationStrengthMetrics:
    """Run the full vibration-strength pipeline on a combined spectrum.

    Detects up to *top_n* local-maxima peaks, estimates the noise floor,
    and returns dB strength for the dominant peak together with the full
    candidate list. Each peak also carries its ``local_floor_amp_g``, what it
    stands out from where it sits (``_peak_local_floors``): a broad hump, such
    as the road ringing a wheel sensor's wheel hop, is the background of the
    peaks on it.

    Returns a dict with keys: ``vibration_strength_db``, ``peak_amp_g``,
    ``noise_floor_amp_g``, ``strength_bucket``, ``top_peaks``.
    """
    freq_arr = np.asarray(freq_hz, dtype=np.float64)
    combined_arr = np.asarray(combined_spectrum_amp_g_values, dtype=np.float64)
    n = min(freq_arr.size, combined_arr.size)
    if n <= 0:
        return empty_vibration_strength_metrics()

    freq = freq_arr[:n]
    combined = np.where(np.isfinite(combined_arr[:n]), np.maximum(combined_arr[:n], 0.0), 0.0)
    floor_p20 = _noise_floor_amp_p20_g_aligned(
        combined_spectrum_amp_g=combined,
        freq_hz=freq,
    )
    threshold = max(
        floor_p20 * PEAK_THRESHOLD_FLOOR_RATIO,
        floor_p20 + STRENGTH_EPSILON_MIN_G,
    )

    floor_peak_limit = max(1, top_n)
    scored_candidate_limit = max(1, top_n * 2)
    scored_candidate_indexes = _candidate_peak_indexes(combined, threshold, scored_candidate_limit)
    floor_peak_indexes = scored_candidate_indexes[:floor_peak_limit]

    base_mask = _range_mask_aligned(freq, strength_range_mask)
    floor_bins = _floor_bins_mask_aligned(
        freq_hz=freq,
        base_mask=base_mask,
        peak_indexes=floor_peak_indexes,
        exclusion_hz=peak_separation_hz,
    )
    floor_strength = _floor_from_bins_aligned(
        amps=combined, base_mask=base_mask, floor_bins=floor_bins
    )
    peak_band_ranges = _peak_band_index_ranges_aligned(
        freq_hz=freq,
        center_indexes=scored_candidate_indexes,
        bandwidth_hz=peak_bandwidth_hz,
    )

    candidate_hz: list[float] = freq[scored_candidate_indexes].tolist()
    if peak_band_ranges is None:
        band_rms_values = np.array(
            [
                _peak_band_rms_amp_g_aligned(
                    freq_hz=freq,
                    combined_spectrum_amp_g=combined,
                    center_idx=idx,
                    bandwidth_hz=peak_bandwidth_hz,
                )
                for idx in scored_candidate_indexes
            ],
            dtype=np.float64,
        )
    else:
        left_bounds, right_bounds = peak_band_ranges
        band_rms_values = _peak_band_rms_amp_g_from_ranges(
            combined_spectrum_amp_g=combined,
            left_bounds=left_bounds,
            right_bounds=right_bounds,
        )
    candidate_db = _batch_vibration_strength_db_aligned(
        peak_band_rms_amp_g_values=band_rms_values,
        floor_amp_g=floor_strength,
    )
    candidate_buckets = _buckets_for_strength_db_aligned(candidate_db)
    candidates: list[tuple[int, StrengthPeak]] = [
        (
            idx,
            {
                "hz": hz,
                "amp": band_rms,
                "vibration_strength_db": db,
                "strength_bucket": strength_bucket,
            },
        )
        for idx, hz, band_rms, db, strength_bucket in zip(
            scored_candidate_indexes,
            candidate_hz,
            band_rms_values.tolist(),
            candidate_db.tolist(),
            candidate_buckets,
            strict=True,
        )
        if isfinite(db)
    ]
    candidates.sort(
        key=lambda item: item[1]["vibration_strength_db"],
        reverse=True,
    )

    chosen: list[StrengthPeak] = []
    chosen_indexes: list[int] = []
    chosen_hz: list[float] = []
    for idx, candidate in candidates:
        if len(chosen) >= top_n:
            break
        hz = candidate["hz"]
        for existing_hz in chosen_hz:
            if abs(existing_hz - hz) < peak_separation_hz:
                break
        else:
            chosen.append(candidate)
            chosen_indexes.append(idx)
            chosen_hz.append(hz)
    local_floors = _peak_local_floors(
        freq_hz=freq,
        combined_spectrum_amp_g=combined,
        floor_bins=floor_bins,
        center_indexes=chosen_indexes,
    )
    for peak, local_floor in zip(chosen, local_floors.tolist(), strict=True):
        peak["local_floor_amp_g"] = local_floor

    top_peak = chosen[0] if chosen else None
    if top_peak is not None:
        _db_val = top_peak.get("vibration_strength_db")
        top_db = float(_db_val) if _db_val is not None else 0.0
        _amp_val = top_peak.get("amp")
        peak_amp_g = float(_amp_val) if _amp_val is not None else 0.0
        _bucket_val = top_peak.get("strength_bucket")
        strength_bucket = _bucket_val if _bucket_val is not None else bucket_for_strength(top_db)
    else:
        top_db = 0.0
        peak_amp_g = 0.0
        strength_bucket = bucket_for_strength(top_db)

    return {
        "vibration_strength_db": top_db,
        "peak_amp_g": peak_amp_g,
        "noise_floor_amp_g": float(floor_strength),
        "strength_bucket": strength_bucket,
        "top_peaks": list(chosen),
    }


# ---------------------------------------------------------------------------
# Convenience wrappers for callers that already have amplitude pairs
# ---------------------------------------------------------------------------


def compute_db(peak_amplitude_g: float, noise_floor_g: float) -> float:
    """Compute vibration strength in dB from an amplitude pair.

    Uses the canonical formula:
    ``20 × log₁₀((peak + ε) / (floor + ε))``
    where ``ε = max(1e-9, floor × 0.05)``.
    """
    return vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak_amplitude_g,
        floor_amp_g=noise_floor_g,
    )


def compute_db_or_none(
    peak_amplitude_g: float | None,
    noise_floor_g: float | None,
) -> float | None:
    """Like :func:`compute_db` but returns ``None`` when either input is ``None``."""
    if peak_amplitude_g is None or noise_floor_g is None:
        return None
    return vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak_amplitude_g,
        floor_amp_g=noise_floor_g,
    )
