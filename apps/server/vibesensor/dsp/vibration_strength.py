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
from dataclasses import dataclass
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
    "StrengthRows",
    "STRENGTH_ALGORITHM_VERSION",
    "STRENGTH_EPSILON_FLOOR_RATIO",
    "STRENGTH_EPSILON_MIN_G",
    "combined_spectrum_amp_g",
    "compute_vibration_strength_db",
    "compute_vibration_strength_rows",
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


@dataclass(frozen=True, slots=True, eq=False)
class StrengthRows:
    """Many spectra's strengths (``compute_vibration_strength_rows``), as columns.

    Per spectrum (row), its noise floor. Per peak, row by row, each row's in
    rank order: its row, frequency, band amplitude, strength (dB) and local
    floor; and where each row's peaks start (one more entry than rows). A
    row's strength is its first peak's.
    """

    noise_floor_amp_g: npt.NDArray[np.float64]
    peak_row: npt.NDArray[np.intp]
    peak_hz: npt.NDArray[np.float64]
    peak_amp: npt.NDArray[np.float64]
    peak_db: npt.NDArray[np.float64]
    peak_local_floor_amp_g: npt.NDArray[np.float64]
    peak_start: npt.NDArray[np.intp]

    def first_peak(self, column: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Each row's first peak's value in *column*, a peak column; 0.0 without peaks."""
        firsts = np.zeros(self.peak_start.size - 1, dtype=np.float64)
        has_peaks = self.peak_start[1:] > self.peak_start[:-1]
        firsts[has_peaks] = column[self.peak_start[:-1][has_peaks]]
        return firsts

    def strength_buckets(self) -> list[str]:
        """Each row's strength bucket: its first peak's, or that of 0 dB without peaks."""
        return _buckets_for_strength_db_aligned(self.first_peak(self.peak_db))

    def metrics(self, row: int) -> VibrationStrengthMetrics:
        """Row *row*'s strength, as ``compute_vibration_strength_db`` has it."""
        start, stop = int(self.peak_start[row]), int(self.peak_start[row + 1])
        top_peaks: list[StrengthPeak] = [
            {
                "hz": hz,
                "amp": amp,
                "vibration_strength_db": db,
                "strength_bucket": strength_bucket,
                "local_floor_amp_g": local_floor,
            }
            for hz, amp, db, strength_bucket, local_floor in zip(
                self.peak_hz[start:stop].tolist(),
                self.peak_amp[start:stop].tolist(),
                self.peak_db[start:stop].tolist(),
                _buckets_for_strength_db_aligned(self.peak_db[start:stop]),
                self.peak_local_floor_amp_g[start:stop].tolist(),
                strict=True,
            )
        ]
        top_peak = top_peaks[0] if top_peaks else None
        return {
            "vibration_strength_db": top_peak["vibration_strength_db"] if top_peak else 0.0,
            "peak_amp_g": top_peak["amp"] if top_peak else 0.0,
            "noise_floor_amp_g": float(self.noise_floor_amp_g[row]),
            "strength_bucket": (
                top_peak["strength_bucket"] if top_peak else bucket_for_strength(0.0)
            ),
            "top_peaks": top_peaks,
        }


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
    return float(_row_quantiles(values[None, :], q)[0])


def _row_quantiles(rows: npt.NDArray[np.floating], q: float) -> npt.NDArray[np.float64]:
    """Each row's linear-interpolation quantile *q*; 0.0 for empty rows.

    Of float32 rows as of the same values in float64: the order statistics
    are taken in the rows' own type (exact, and faster), the interpolation in
    float64.
    """
    if rows.shape[1] == 0:
        return np.zeros(rows.shape[0], dtype=np.float64)
    q_value = float(q)
    if not 0.0 <= q_value <= 1.0:
        return np.asarray(np.quantile(rows, q_value, axis=1), dtype=np.float64)
    if rows.shape[1] == 1:
        return rows[:, 0].astype(np.float64)
    if q_value == 0.0:
        return np.min(rows, axis=1).astype(np.float64, copy=False)
    if q_value == 1.0:
        return np.max(rows, axis=1).astype(np.float64, copy=False)

    # The linear-interpolation quantile only needs the two bracketing order
    # statistics, so use partition instead of the heavier generic quantile path:
    # on the upper one, the lower one being the largest of those before it.
    position = q_value * float(rows.shape[1] - 1)
    lower_idx = int(position)
    upper_idx = int(np.ceil(position))
    partitioned = np.partition(rows, upper_idx, axis=1)
    upper_value = partitioned[:, upper_idx].astype(np.float64)
    if lower_idx == upper_idx:
        return upper_value
    lower_value = np.max(partitioned[:, :upper_idx], axis=1).astype(np.float64)
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
    values: npt.NDArray[np.floating],
    counted: npt.NDArray[np.bool_],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.intp]]:
    """Per row, the median of *values* over the *counted* entries, and their count.

    Sorted in the values' own type (float32 sorts faster, to the same order),
    averaged in float64.
    """
    ordered = np.where(counted, values, np.inf)
    ordered.sort(axis=1)
    counts = np.count_nonzero(counted, axis=1)
    rows = np.arange(values.shape[0])
    lower = ordered[rows, np.maximum(counts - 1, 0) // 2]
    upper = ordered[rows, np.minimum(counts // 2, values.shape[1] - 1)]
    return 0.5 * np.add(lower, upper, dtype=np.float64), counts


def _peak_local_floors(
    *,
    freq_hz: npt.NDArray[np.float64],
    spectra: npt.NDArray[np.floating],
    floor_bins: npt.NDArray[np.bool_],
    rows: npt.NDArray[np.intp],
    center_indexes: npt.NDArray[np.intp],
) -> npt.NDArray[np.float64]:
    """What each peak (of ``spectra[rows]``) stands out from where it sits: its local floor.

    The median of the floor bins within ``LOCAL_FLOOR_HALF_WIDTH_HZ`` of the
    peak. Where peaks crowd that whole neighbourhood (no floor bin left), the
    median of every bin there: a peak among many is as strong as its crowd.
    """
    if not center_indexes.size:
        return np.empty(0, dtype=np.float64)
    bin_hz = float(freq_hz[1] - freq_hz[0]) if freq_hz.size > 1 else 0.0
    half_bins = int(round(LOCAL_FLOOR_HALF_WIDTH_HZ / bin_hz)) if bin_hz > 0 else 0
    index = center_indexes[:, None] + np.arange(-half_bins, half_bins + 1, dtype=np.intp)[None, :]
    inside = (index >= 0) & (index < freq_hz.size)
    index = np.clip(index, 0, freq_hz.size - 1)
    values = spectra[rows[:, None], index]
    floors, floor_counts = _window_medians(values, inside & floor_bins[rows[:, None], index])
    crowded = floor_counts == 0
    if crowded.any():
        crowd_medians, _counts = _window_medians(values[crowded], inside[crowded])
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


def _candidate_peaks(
    spectra: npt.NDArray[np.floating], thresholds: npt.NDArray[np.float64], limit: int
) -> tuple[npt.NDArray[np.intp], npt.NDArray[np.intp], npt.NDArray[np.intp]]:
    """Per spectrum, its *limit* highest local maxima at or above its threshold, highest first.

    The last bin also counts where it rises above its neighbour. Of equal
    maxima, the higher bin comes first. Returns each one's spectrum (row), bin
    and rank, row by row.
    """
    size = spectra.shape[1]
    is_peak = np.zeros(spectra.shape, dtype=np.bool_)
    if size >= 3:
        left, right = spectra[:, :-1], spectra[:, 1:]
        is_peak[:, 1:-1] = (right[:, :-1] > left[:, :-1]) & (left[:, 1:] > right[:, 1:])
        for row in np.flatnonzero((left == right).any(axis=1)).tolist():
            # A flat top counts once, at its middle (``_local_maxima``).
            is_peak[row] = False
            is_peak[row, _local_maxima(spectra[row])] = True
    if size > 1:
        is_peak[:, -1] = spectra[:, -1] > spectra[:, -2]
    is_peak &= spectra >= thresholds[:, None]
    # Each row's maxima from its last bin back, so that ranking them (a stable
    # sort) puts the higher bin of equal ones first.
    peak_rows, peak_indexes = (found[::-1] for found in np.nonzero(is_peak))
    order = np.lexsort((-spectra[peak_rows, peak_indexes], peak_rows))
    peak_rows, peak_indexes = peak_rows[order], peak_indexes[order]
    ranks = np.arange(peak_rows.size) - np.searchsorted(peak_rows, peak_rows)
    kept = ranks < limit
    return peak_rows[kept], peak_indexes[kept], ranks[kept]


def _floor_bins(
    *,
    freq_hz: npt.NDArray[np.float64],
    base_mask: npt.NDArray[np.bool_],
    rows: npt.NDArray[np.intp],
    peak_indexes: npt.NDArray[np.intp],
    row_count: int,
    exclusion_hz: float,
) -> npt.NDArray[np.bool_]:
    """Per spectrum (row), the in-range bins outside *exclusion_hz* of each of its peaks.

    The peaks are given by their row and bin.
    """
    size = freq_hz.size
    if np.any(freq_hz[1:] < freq_hz[:-1]):
        return np.array(
            [
                _floor_bins_mask_aligned(
                    freq_hz=freq_hz,
                    base_mask=base_mask,
                    peak_indexes=peak_indexes[rows == row].tolist(),
                    exclusion_hz=exclusion_hz,
                )
                for row in range(row_count)
            ],
            dtype=np.bool_,
        ).reshape(row_count, size)
    # Each peak's excluded bins [left, right), every one of them, flat over the rows.
    centre_hz = freq_hz[peak_indexes]
    lefts = np.searchsorted(freq_hz, centre_hz - exclusion_hz, side="left")
    lengths = np.searchsorted(freq_hz, centre_hz + exclusion_hz, side="right") - lefts
    firsts = rows * size + lefts - (np.cumsum(lengths) - lengths)
    excluded = np.zeros(row_count * size, dtype=np.bool_)
    excluded[np.repeat(firsts, lengths) + np.arange(int(lengths.sum()))] = True
    floor_bins: npt.NDArray[np.bool_] = base_mask & ~excluded.reshape(row_count, size)
    return floor_bins


# A bin and its neighbours, as offsets.
_NEIGHBOURS: Final[npt.NDArray[np.intp]] = np.array([-1, 0, 1], dtype=np.intp)


def _interpolated_peak_hz(
    freq_hz: npt.NDArray[np.float64],
    spectra: npt.NDArray[np.floating],
    rows: npt.NDArray[np.intp],
    indexes: npt.NDArray[np.intp],
) -> npt.NDArray[np.float64]:
    """Each peak's frequency between bins, from a parabola through its bins' log amplitudes.

    The parabola runs through the peak bin and its two neighbours. A tone's
    Hann-windowed peak is close to a Gaussian, whose log is that parabola, so
    its vertex lands within a few hundredths of a bin of the tone, where the
    peak bin alone is up to half a bin off. A peak on the spectrum's edge or
    beside a zero keeps its bin's frequency.
    """
    hz = freq_hz[indexes]
    inner = (indexes > 0) & (indexes < spectra.shape[1] - 1)
    row, idx = rows[inner], indexes[inner]
    with np.errstate(divide="ignore", invalid="ignore"):
        logs = np.log(spectra[row[:, None], idx[:, None] + _NEIGHBOURS], dtype=np.float64)
        log_l, log_c, log_r = logs[:, 0], logs[:, 1], logs[:, 2]
        offset = 0.5 * (log_l - log_r) / (log_l - 2.0 * log_c + log_r)
    bin_hz = freq_hz[idx + 1] - freq_hz[idx]
    hz[inner] = np.where(
        np.isfinite(offset), freq_hz[idx] + np.clip(offset, -0.5, 0.5) * bin_hz, freq_hz[idx]
    )
    return hz


def _peak_band_rms_amp_g(
    *,
    freq_hz: npt.NDArray[np.float64],
    spectra: npt.NDArray[np.floating],
    rows: npt.NDArray[np.intp],
    center_indexes: npt.NDArray[np.intp],
    bandwidth_hz: float,
) -> npt.NDArray[np.float64]:
    """Each peak's RMS amplitude (g) over the bins of its spectrum within *bandwidth_hz*."""
    if np.any(freq_hz[1:] < freq_hz[:-1]):
        return np.array(
            [
                _peak_band_rms_amp_g_aligned(
                    freq_hz=freq_hz,
                    combined_spectrum_amp_g=spectra[row],
                    center_idx=index,
                    bandwidth_hz=bandwidth_hz,
                )
                for row, index in zip(rows.tolist(), center_indexes.tolist(), strict=True)
            ],
            dtype=np.float64,
        )
    center_hz = freq_hz[center_indexes]
    left_bounds = np.searchsorted(freq_hz, center_hz - bandwidth_hz, side="left")
    right_bounds = np.searchsorted(freq_hz, center_hz + bandwidth_hz, side="right")
    # Each spectrum's running sum of squares: a band's sum is the difference
    # of those at its last bin and before its first (0 before the first bin).
    running = np.square(spectra, dtype=np.float64)
    np.cumsum(running, axis=1, out=running)
    counts = right_bounds - left_bounds
    result = np.zeros(center_indexes.shape, dtype=np.float64)
    valid = counts > 0
    if np.any(valid):
        band_rows, lefts = rows[valid], left_bounds[valid]
        before = np.where(lefts > 0, running[band_rows, np.maximum(lefts - 1, 0)], 0.0)
        sums = running[band_rows, right_bounds[valid] - 1] - before
        result[valid] = np.sqrt(sums / counts[valid])
    return result


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
    combined_arr = np.asarray(combined_spectrum_amp_g_values)
    n = min(freq_arr.size, combined_arr.size)
    if n <= 0:
        return empty_vibration_strength_metrics()
    return compute_vibration_strength_rows(
        freq_hz=freq_arr[:n],
        spectra=combined_arr[None, :n],
        peak_bandwidth_hz=peak_bandwidth_hz,
        peak_separation_hz=peak_separation_hz,
        top_n=top_n,
        strength_range_mask=strength_range_mask,
    ).metrics(0)


def compute_vibration_strength_rows(
    *,
    freq_hz: npt.NDArray[np.floating],
    spectra: npt.NDArray[np.floating],
    peak_bandwidth_hz: float = PEAK_BANDWIDTH_HZ,
    peak_separation_hz: float = PEAK_SEPARATION_HZ,
    top_n: int = 5,
    strength_range_mask: npt.NDArray[np.bool_] | None = None,
) -> StrengthRows:
    """``compute_vibration_strength_db`` of each row of *spectra*, all on the bins *freq_hz*.

    Many spectra at once take a fraction of the time of one call each (the
    post-stop raw replay); each row's result is the one it has on its own.
    Float32 spectra (as the FFT gives them) are taken as the same values in
    float64: their order statistics are taken in float32, which is exact and
    faster, everything else in float64. There must be at least one bin.
    """
    if freq_hz.size == 0:
        raise ValueError("strength rows need at least one frequency bin")
    freq = np.asarray(freq_hz, dtype=np.float64)
    if spectra.dtype != np.float32:
        spectra = spectra.astype(np.float64, copy=False)
    combined = np.maximum(spectra, 0.0)
    if not np.isfinite(combined).all():
        combined = np.where(np.isfinite(combined), combined, 0.0)
    row_count = combined.shape[0]
    noise_bins = combined[:, 1:] if _spectrum_includes_dc_bin_aligned(freq_hz=freq) else combined
    floor_p20 = _row_quantiles(noise_bins, 0.20)
    thresholds = np.maximum(
        floor_p20 * PEAK_THRESHOLD_FLOOR_RATIO, floor_p20 + STRENGTH_EPSILON_MIN_G
    )

    rows, indexes, ranks = _candidate_peaks(combined, thresholds, max(1, top_n * 2))
    base_mask = _range_mask_aligned(freq, strength_range_mask)
    floor_peaks = ranks < max(1, top_n)
    floor_bins = _floor_bins(
        freq_hz=freq,
        base_mask=base_mask,
        rows=rows[floor_peaks],
        peak_indexes=indexes[floor_peaks],
        row_count=row_count,
        exclusion_hz=peak_separation_hz,
    )
    floor_strengths, floor_counts = _window_medians(combined, floor_bins)
    for row in np.flatnonzero(floor_counts == 0).tolist():
        # All bins were within peak exclusion zones: P20 of the in-range bins
        # (not ``noise_floor_amp_p20_g``, which assumes a DC bin to skip).
        floor_strengths[row] = _quantile_or_zero(combined[row][base_mask], 0.20)

    candidate_hz = _interpolated_peak_hz(freq, combined, rows, indexes)
    band_rms_values = _peak_band_rms_amp_g(
        freq_hz=freq,
        spectra=combined,
        rows=rows,
        center_indexes=indexes,
        bandwidth_hz=peak_bandwidth_hz,
    )
    floors = np.where(np.isfinite(floor_strengths), np.maximum(floor_strengths, 0.0), 0.0)
    epsilons = np.maximum(STRENGTH_EPSILON_MIN_G, floors * STRENGTH_EPSILON_FLOOR_RATIO)
    band = np.where(np.isfinite(band_rms_values), np.maximum(band_rms_values, 0.0), 0.0)
    candidate_db = 20.0 * np.log10((band + epsilons[rows]) / (floors[rows] + epsilons[rows]))

    # Each row's candidates with a finite strength, strongest first; equal
    # strengths keep their order (a stable sort, as ``list.sort``). Then, in
    # that order, those at least ``peak_separation_hz`` from every one chosen
    # before them, up to ``top_n``.
    finite = np.flatnonzero(np.isfinite(candidate_db))
    ranked = finite[np.lexsort((-candidate_db[finite], rows[finite]))]
    chosen: list[int] = []
    chosen_hz: list[float] = []
    current_row = -1
    for position, row, hz in zip(
        ranked.tolist(), rows[ranked].tolist(), candidate_hz[ranked].tolist(), strict=True
    ):
        if row != current_row:
            current_row = row
            chosen_hz = []
        if len(chosen_hz) >= top_n:
            continue
        for existing_hz in chosen_hz:
            if abs(existing_hz - hz) < peak_separation_hz:
                break
        else:
            chosen.append(position)
            chosen_hz.append(hz)

    picked = np.asarray(chosen, dtype=np.intp)
    peak_row = rows[picked]
    peak_start = np.zeros(row_count + 1, dtype=np.intp)
    np.cumsum(np.bincount(peak_row, minlength=row_count), out=peak_start[1:])
    return StrengthRows(
        noise_floor_amp_g=floor_strengths,
        peak_row=peak_row,
        peak_hz=candidate_hz[picked],
        peak_amp=band_rms_values[picked],
        peak_db=candidate_db[picked],
        peak_local_floor_amp_g=_peak_local_floors(
            freq_hz=freq,
            spectra=combined,
            floor_bins=floor_bins,
            rows=peak_row,
            center_indexes=indexes[picked],
        ),
        peak_start=peak_start,
    )


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
