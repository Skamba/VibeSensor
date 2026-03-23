"""Shared statistical helpers for diagnostics peak scoring and reporting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import sqrt

from vibesensor.vibration_strength import percentile


def _safe_percentile(sorted_vals: Sequence[float], q: float, *, default: float = 0.0) -> float:
    if len(sorted_vals) >= 2:
        return float(percentile(list(sorted_vals), q))
    return float(sorted_vals[-1]) if sorted_vals else default


@dataclass(frozen=True, slots=True)
class PeakDistributionStats:
    """Shared amplitude and floor statistics for one accumulated peak bin."""

    sample_count: int
    median_amp: float
    p95_amp: float
    max_amp: float
    burstiness: float
    mean_floor_amp: float | None
    median_floor_amp: float | None


def compute_peak_distribution_stats(
    amps: Sequence[float],
    floor_amps: Sequence[float],
) -> PeakDistributionStats:
    """Compute canonical per-bin amplitude and floor statistics."""
    sorted_amps = sorted(float(amp) for amp in amps)
    if not sorted_amps:
        raise ValueError("peak-bin statistics require at least one amplitude value")
    sorted_floors = sorted(float(floor) for floor in floor_amps)
    median_amp = _safe_percentile(sorted_amps, 0.50)
    p95_amp = _safe_percentile(sorted_amps, 0.95)
    max_amp = sorted_amps[-1]
    burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0
    mean_floor_amp = sum(sorted_floors) / len(sorted_floors) if sorted_floors else None
    median_floor_amp = _safe_percentile(sorted_floors, 0.50, default=0.0) if sorted_floors else None
    return PeakDistributionStats(
        sample_count=len(sorted_amps),
        median_amp=median_amp,
        p95_amp=p95_amp,
        max_amp=max_amp,
        burstiness=burstiness,
        mean_floor_amp=mean_floor_amp,
        median_floor_amp=median_floor_amp,
    )


def compute_peak_speed_uniformity(
    *,
    speed_bin_counts_for_bin: Mapping[str, int],
    total_speed_bin_counts: Mapping[str, int],
) -> float | None:
    """Compute the std-dev of hit rates across populated speed bins."""
    if len(total_speed_bin_counts) < 2:
        return None
    hit_rate_sum = 0.0
    hit_rate_sq_sum = 0.0
    hit_rate_count = 0
    for speed_bin, total_count in total_speed_bin_counts.items():
        if total_count <= 0:
            continue
        rate = speed_bin_counts_for_bin.get(speed_bin, 0) / total_count
        hit_rate_sum += rate
        hit_rate_sq_sum += rate * rate
        hit_rate_count += 1
    if hit_rate_count > 1:
        hit_rate_mean = hit_rate_sum / hit_rate_count
        variance = max(0.0, (hit_rate_sq_sum / hit_rate_count) - hit_rate_mean * hit_rate_mean)
        return sqrt(variance)
    if hit_rate_count == 1:
        return 0.0
    return None


def compute_peak_spatial_uniformity(
    *,
    matching_locations: int,
    total_locations: int,
) -> float | None:
    """Compute simple location coverage ratio when multiple sensors were present."""
    if total_locations < 2:
        return None
    return matching_locations / total_locations


def compute_peak_persistence_score(*, presence_ratio: float, p95_amp: float) -> float:
    """Compute the shared persistence-weighted ranking score for a peak bin."""
    return (presence_ratio**2) * p95_amp
