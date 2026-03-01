from __future__ import annotations

from math import isfinite, log10, sqrt
from typing import Any

from .strength_bands import bucket_for_strength

PEAK_BANDWIDTH_HZ = 1.2
PEAK_SEPARATION_HZ = 1.2

STRENGTH_EPSILON_MIN_G = 1e-9
STRENGTH_EPSILON_FLOOR_RATIO = 0.05
PEAK_THRESHOLD_FLOOR_RATIO = 2.6


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 0:
        return float(ordered[mid - 1] + ordered[mid]) / 2.0
    return float(ordered[mid])


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    clamped = max(0.0, min(1.0, float(q)))
    pos = clamped * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(len(sorted_values) - 1, lo + 1)
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] + ((sorted_values[hi] - sorted_values[lo]) * frac))


def combined_spectrum_amp_g(
    *, axis_spectra_amp_g: list[list[float]], axis_count_for_mean: int | None = None
) -> list[float]:
    """
    Canonical combined spectrum amplitude definition.

    Input axis arrays must be single-sided FFT amplitude magnitudes in g.
    Output is sqrt(mean(axis_amp^2)) per frequency bin,
    i.e. sqrt((x^2+y^2+z^2)/3) when 3 axes exist.
    """
    if not axis_spectra_amp_g:
        return []
    target_len = min((len(axis) for axis in axis_spectra_amp_g), default=0)
    if target_len <= 0:
        return []
    divisor = (
        max(1.0, float(axis_count_for_mean))
        if axis_count_for_mean is not None
        else max(1.0, float(len(axis_spectra_amp_g)))
    )
    out: list[float] = [0.0] * target_len
    for idx in range(target_len):
        sq_sum = 0.0
        for axis_values in axis_spectra_amp_g:
            value = float(axis_values[idx])
            sq_sum += value * value
        out[idx] = sqrt(sq_sum / divisor)
    return out


def noise_floor_amp_p20_g(*, combined_spectrum_amp_g: list[float]) -> float:
    if not combined_spectrum_amp_g:
        return 0.0
    band = (
        combined_spectrum_amp_g[1:]
        if len(combined_spectrum_amp_g) > 1
        else combined_spectrum_amp_g
    )
    finite = sorted(value for value in band if isfinite(value) and value >= 0.0)
    return percentile(finite, 0.20)


def strength_floor_amp_g(
    *,
    freq_hz: list[float],
    combined_spectrum_amp_g: list[float],
    peak_indexes: list[int],
    exclusion_hz: float,
    min_hz: float,
    max_hz: float,
) -> float:
    if not freq_hz or not combined_spectrum_amp_g:
        return 0.0
    n = min(len(freq_hz), len(combined_spectrum_amp_g))
    if n <= 0:
        return 0.0
    peak_hz = [float(freq_hz[idx]) for idx in peak_indexes if 0 <= idx < n]
    selected: list[float] = []
    for idx in range(n):
        hz = float(freq_hz[idx])
        if hz < min_hz or hz > max_hz:
            continue
        if any(abs(hz - center_hz) <= exclusion_hz for center_hz in peak_hz):
            continue
        amp = float(combined_spectrum_amp_g[idx])
        if amp >= 0.0 and isfinite(amp):
            selected.append(amp)
    if not selected:
        # All bins fell within peak exclusion zones; fall back to P20 noise
        # floor to avoid returning 0.0 which would produce ~140 dB artifacts.
        return noise_floor_amp_p20_g(
            combined_spectrum_amp_g=list(combined_spectrum_amp_g[:n]),
        )
    return median(selected)


def peak_band_rms_amp_g(
    *,
    freq_hz: list[float],
    combined_spectrum_amp_g: list[float],
    center_idx: int,
    bandwidth_hz: float,
) -> float:
    n = min(len(freq_hz), len(combined_spectrum_amp_g))
    if not (0 <= center_idx < n):
        return 0.0
    center_hz = float(freq_hz[center_idx])
    sq_sum = 0.0
    count = 0
    for idx in range(n):
        if abs(float(freq_hz[idx]) - center_hz) <= bandwidth_hz:
            amp = float(combined_spectrum_amp_g[idx])
            sq_sum += amp * amp
            count += 1
    if count <= 0:
        return 0.0
    return sqrt(sq_sum / count)


def vibration_strength_db_scalar(
    *,
    peak_band_rms_amp_g: float,
    floor_amp_g: float,
    epsilon_g: float | None = None,
) -> float:
    _floor_raw = float(floor_amp_g)
    _band_raw = float(peak_band_rms_amp_g)
    # Guard against NaN inputs: max(0.0, NaN) returns NaN in CPython.
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
    freq_hz: list[float],
    combined_spectrum_amp_g_values: list[float],
    peak_bandwidth_hz: float = PEAK_BANDWIDTH_HZ,
    peak_separation_hz: float = PEAK_SEPARATION_HZ,
    top_n: int = 5,
) -> dict[str, Any]:
    n = min(len(freq_hz), len(combined_spectrum_amp_g_values))
    if n <= 0:
        return {
            "combined_spectrum_amp_g": [],
            "vibration_strength_db": 0.0,
            "peak_amp_g": 0.0,
            "noise_floor_amp_g": 0.0,
            "strength_bucket": None,
            "top_peaks": [],
        }

    freq = [float(v) for v in freq_hz[:n]]
    combined = [max(0.0, float(v)) for v in combined_spectrum_amp_g_values[:n]]
    floor_p20 = noise_floor_amp_p20_g(combined_spectrum_amp_g=combined)
    threshold = max(
        floor_p20 * PEAK_THRESHOLD_FLOOR_RATIO,
        floor_p20 + STRENGTH_EPSILON_MIN_G,
    )

    local_maxima: list[int] = []
    for idx in range(1, n - 1):
        value = combined[idx]
        if value < threshold:
            continue
        if value > combined[idx - 1] and value >= combined[idx + 1]:
            local_maxima.append(idx)
    # Boundary check: last bin can be a peak if it exceeds its left neighbor.
    if n > 1:
        last_val = combined[n - 1]
        if last_val >= threshold and last_val > combined[n - 2]:
            local_maxima.append(n - 1)
    local_maxima.sort(key=lambda idx: combined[idx], reverse=True)
    peak_indexes = local_maxima[: max(1, top_n)]

    floor_strength = strength_floor_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=combined,
        peak_indexes=peak_indexes,
        exclusion_hz=peak_separation_hz,
        min_hz=freq[0] if freq else 0.0,
        max_hz=freq[-1] if freq else 0.0,
    )

    candidates: list[dict[str, float | str | None]] = []
    for idx in local_maxima:
        band_rms = peak_band_rms_amp_g(
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
    candidates.sort(
        key=lambda item: float(
            item["vibration_strength_db"]
            if item["vibration_strength_db"] is not None
            else -1e9
        ),
        reverse=True,
    )

    chosen: list[dict[str, float | str | None]] = []
    for candidate in candidates:
        if len(chosen) >= top_n:
            break
        hz = float(candidate["hz"] or 0.0)
        if any(
            abs(float(existing["hz"] or 0.0) - hz) < peak_separation_hz
            for existing in chosen
        ):
            continue
        chosen.append(candidate)

    top_peak = chosen[0] if chosen else None
    top_db = float((top_peak or {}).get("vibration_strength_db") or 0.0)
    peak_amp_g = float((top_peak or {}).get("amp") or 0.0)

    return {
        "combined_spectrum_amp_g": combined,
        "vibration_strength_db": top_db,
        "peak_amp_g": peak_amp_g,
        "noise_floor_amp_g": float(floor_strength),
        "strength_bucket": bucket_for_strength(top_db),
        "top_peaks": list(chosen),
    }
