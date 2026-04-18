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
from typing import Final, TypedDict, cast

import numpy as np
import numpy.typing as npt

from vibesensor.strength_bands import bucket_for_strength

__all__ = [
    "compute_db",
    "compute_db_or_none",
    "empty_vibration_strength_metrics",
    "PEAK_BANDWIDTH_HZ",
    "PEAK_SEPARATION_HZ",
    "PEAK_THRESHOLD_FLOOR_RATIO",
    "StrengthPeak",
    "STRENGTH_EPSILON_FLOOR_RATIO",
    "STRENGTH_EPSILON_MIN_G",
    "combined_spectrum_amp_g",
    "compute_vibration_strength_db",
    "median",
    "noise_floor_amp_p20_g",
    "peak_band_rms_amp_g",
    "percentile",
    "relative_level_db_scalar",
    "strength_floor_amp_g",
    "VibrationStrengthMetrics",
    "vibration_strength_db_scalar",
]

PEAK_BANDWIDTH_HZ: Final[float] = 1.2
PEAK_SEPARATION_HZ: Final[float] = 1.2
STRENGTH_EPSILON_MIN_G: Final[float] = 1e-9
STRENGTH_EPSILON_FLOOR_RATIO: Final[float] = 0.05
PEAK_THRESHOLD_FLOOR_RATIO: Final[float] = 2.6

ArrayLike = Sequence[float] | npt.NDArray[np.floating]


class StrengthPeak(TypedDict):
    hz: float
    amp: float
    vibration_strength_db: float
    strength_bucket: str | None


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
    return float(np.quantile(values, q))


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
    if isinstance(axis_spectra_amp_g, np.ndarray):
        if axis_spectra_amp_g.size == 0:
            return []
        arr = np.asarray(axis_spectra_amp_g, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
    else:
        if not axis_spectra_amp_g:
            return []
        target_len = min((len(a) for a in axis_spectra_amp_g), default=0)
        if target_len <= 0:
            return []
        arr = np.empty((len(axis_spectra_amp_g), target_len), dtype=np.float64)
        for i, a in enumerate(axis_spectra_amp_g):
            arr[i] = np.asarray(a, dtype=np.float64)[:target_len]

    arr = np.where(np.isfinite(arr), arr, 0.0)
    divisor = (
        max(1.0, float(axis_count_for_mean))
        if axis_count_for_mean is not None
        else max(1.0, float(arr.shape[0]))
    )
    result: npt.NDArray[np.floating] = np.sqrt(np.sum(arr**2, axis=0) / divisor)
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
    return _noise_floor_amp_p20_g_aligned(combined_spectrum_amp_g=band)


def _noise_floor_amp_p20_g_aligned(*, combined_spectrum_amp_g: npt.NDArray[np.float64]) -> float:
    band = combined_spectrum_amp_g
    if band.size <= 1:
        # Empty spectrum or DC-only: no frequency content to estimate noise from.
        return 0.0
    finite = band[1:]
    finite = finite[np.isfinite(finite) & (finite >= 0.0)]
    return _quantile_or_zero(finite, 0.20)


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
    return _strength_floor_amp_g_aligned(
        freq_hz=freq,
        combined_spectrum_amp_g=amps,
        peak_indexes=peak_indexes,
        exclusion_hz=exclusion_hz,
        min_hz=min_hz,
        max_hz=max_hz,
    )


def _strength_floor_amp_g_aligned(
    *,
    freq_hz: npt.NDArray[np.float64],
    combined_spectrum_amp_g: npt.NDArray[np.float64],
    peak_indexes: list[int],
    exclusion_hz: float,
    min_hz: float,
    max_hz: float,
) -> float:
    freq = freq_hz
    amps = combined_spectrum_amp_g
    if freq.size == 0:
        return 0.0
    in_range = (freq >= min_hz) & (freq <= max_hz)
    valid_amp = np.isfinite(amps) & (amps >= 0.0)
    selected_mask = in_range & valid_amp
    peak_idx = [idx for idx in peak_indexes if 0 <= idx < freq.size]
    if peak_idx:
        _exclude_peak_regions_aligned(
            selected_mask=selected_mask,
            freq_hz=freq,
            peak_indexes=peak_idx,
            exclusion_hz=exclusion_hz,
        )
    selected = amps[selected_mask]
    if selected.size == 0:
        # All bins were within peak exclusion zones.  Compute P20 of all
        # qualifying in-range bins instead of delegating to
        # noise_floor_amp_p20_g, which unconditionally skips index 0
        # (assuming DC content at 0 Hz) — an assumption that breaks when
        # the caller has already stripped the DC bin from the spectrum.
        return _quantile_or_zero(amps[in_range & valid_amp], 0.20)
    return float(np.median(selected))


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


def _peak_band_rms_amp_g_from_bounds(
    *,
    combined_spectrum_amp_g: npt.NDArray[np.float64],
    start_idx: int,
    stop_idx: int,
) -> float:
    band = combined_spectrum_amp_g[start_idx:stop_idx]
    if band.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(band, dtype=np.float64))))


def _local_maxima_indexes(values: npt.NDArray[np.float64], threshold: float) -> list[int]:
    maxima: list[int] = []
    if values.size > 2:
        interior = values[1:-1]
        mask = (interior >= threshold) & (interior > values[:-2]) & (interior >= values[2:])
        maxima.extend((np.flatnonzero(mask) + 1).tolist())
    if values.size > 1:
        last_val = float(values[-1])
        if last_val >= threshold and last_val > float(values[-2]):
            maxima.append(values.size - 1)
    maxima.sort(key=lambda idx: float(values[idx]), reverse=True)
    return maxima


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
) -> VibrationStrengthMetrics:
    """Run the full vibration-strength pipeline on a combined spectrum.

    Detects up to *top_n* local-maxima peaks, estimates the noise floor,
    and returns dB strength for the dominant peak together with the full
    candidate list.

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
    floor_p20 = _noise_floor_amp_p20_g_aligned(combined_spectrum_amp_g=combined)
    threshold = max(
        floor_p20 * PEAK_THRESHOLD_FLOOR_RATIO,
        floor_p20 + STRENGTH_EPSILON_MIN_G,
    )

    local_maxima = _local_maxima_indexes(combined, threshold)
    invalid_idx = next((idx for idx in local_maxima if not (0 <= idx < freq.size)), None)
    if invalid_idx is not None:
        raise ValueError(
            f"peak index {invalid_idx} out of range for aligned spectrum size {freq.size}"
        )
    floor_peak_limit = max(1, top_n)
    scored_candidate_limit = max(1, top_n * 2)
    scored_candidate_indexes = [int(idx) for idx in local_maxima[:scored_candidate_limit]]
    floor_peak_indexes = scored_candidate_indexes[:floor_peak_limit]

    floor_strength = _strength_floor_amp_g_aligned(
        freq_hz=freq,
        combined_spectrum_amp_g=combined,
        peak_indexes=floor_peak_indexes,
        exclusion_hz=peak_separation_hz,
        min_hz=float(freq[0]) if freq.size else 0.0,
        max_hz=float(freq[-1]) if freq.size else 0.0,
    )
    peak_band_ranges = _peak_band_index_ranges_aligned(
        freq_hz=freq,
        center_indexes=scored_candidate_indexes,
        bandwidth_hz=peak_bandwidth_hz,
    )

    candidates: list[StrengthPeak] = []
    if peak_band_ranges is None:
        for idx in scored_candidate_indexes:
            band_rms = _peak_band_rms_amp_g_aligned(
                freq_hz=freq,
                combined_spectrum_amp_g=combined,
                center_idx=idx,
                bandwidth_hz=peak_bandwidth_hz,
            )
            db = vibration_strength_db_scalar(
                peak_band_rms_amp_g=band_rms,
                floor_amp_g=floor_strength,
            )
            if not isfinite(db):
                continue
            candidates.append(
                {
                    "hz": float(freq[idx]),
                    "amp": float(band_rms),
                    "vibration_strength_db": float(db),
                    "strength_bucket": bucket_for_strength(float(db)),
                }
            )
    else:
        left_bounds, right_bounds = peak_band_ranges
        for candidate_idx, idx in enumerate(scored_candidate_indexes):
            band_rms = _peak_band_rms_amp_g_from_bounds(
                combined_spectrum_amp_g=combined,
                start_idx=int(left_bounds[candidate_idx]),
                stop_idx=int(right_bounds[candidate_idx]),
            )
            db = vibration_strength_db_scalar(
                peak_band_rms_amp_g=band_rms,
                floor_amp_g=floor_strength,
            )
            if not isfinite(db):
                continue
            candidates.append(
                {
                    "hz": float(freq[idx]),
                    "amp": float(band_rms),
                    "vibration_strength_db": float(db),
                    "strength_bucket": bucket_for_strength(float(db)),
                }
            )
    candidates.sort(
        key=lambda item: item["vibration_strength_db"],
        reverse=True,
    )

    chosen: list[StrengthPeak] = []
    for candidate in candidates:
        if len(chosen) >= top_n:
            break
        hz = float(candidate["hz"] or 0.0)
        if any(abs(float(existing["hz"] or 0.0) - hz) < peak_separation_hz for existing in chosen):
            continue
        chosen.append(candidate)

    top_peak = chosen[0] if chosen else None
    if top_peak is not None:
        _db_val = top_peak.get("vibration_strength_db")
        top_db = float(_db_val) if _db_val is not None else 0.0
        _amp_val = top_peak.get("amp")
        peak_amp_g = float(_amp_val) if _amp_val is not None else 0.0
    else:
        top_db = 0.0
        peak_amp_g = 0.0

    return {
        "vibration_strength_db": top_db,
        "peak_amp_g": peak_amp_g,
        "noise_floor_amp_g": float(floor_strength),
        "strength_bucket": bucket_for_strength(top_db),
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


def relative_level_db_scalar(level_amp_g: float, reference_amp_g: float) -> float:
    """Compute a relative dB level against a reference amplitude.

    Uses the canonical vibration-strength formula so report-facing relative views
    stay aligned with the repo's single dB definition while still producing
    intuitive ``0 dB`` strongest-row values and negative offsets for weaker
    sensor observations.
    """
    return vibration_strength_db_scalar(
        peak_band_rms_amp_g=level_amp_g,
        floor_amp_g=reference_amp_g,
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
