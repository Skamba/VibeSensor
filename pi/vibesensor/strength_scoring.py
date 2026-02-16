from __future__ import annotations

from math import log10, sqrt


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[len(ordered) // 2])


def compute_floor_rms(
    *,
    freq: list[float],
    values: list[float],
    peak_indexes: list[int],
    exclusion_hz: float,
    min_hz: float,
    max_hz: float,
) -> float:
    if not freq or not values:
        return 0.0
    selected: list[float] = []
    peak_hz = [freq[idx] for idx in peak_indexes if 0 <= idx < len(freq)]
    for idx, hz in enumerate(freq):
        if hz < min_hz or hz > max_hz:
            continue
        if any(abs(hz - p_hz) <= exclusion_hz for p_hz in peak_hz):
            continue
        selected.append(values[idx])
    return _median(selected)


def compute_band_rms(*, freq: list[float], values: list[float], center_idx: int, bandwidth_hz: float) -> float:
    if not (0 <= center_idx < len(values)):
        return 0.0
    center_hz = freq[center_idx]
    sq_sum = 0.0
    count = 0
    for idx, hz in enumerate(freq):
        if abs(hz - center_hz) <= bandwidth_hz:
            amp = values[idx]
            sq_sum += amp * amp
            count += 1
    if count <= 0:
        return 0.0
    return sqrt(sq_sum / count)


def strength_db_above_floor(*, band_rms: float, floor_rms: float) -> float:
    eps = max(1e-9, floor_rms * 0.05)
    return 20.0 * log10((band_rms + eps) / (floor_rms + eps))
