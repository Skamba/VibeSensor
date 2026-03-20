"""Speed-profile helper functions shared across diagnostics modules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from math import sqrt

from vibesensor.domain import SpeedProfileSummary
from vibesensor.domain.finding import speed_band_sort_key, speed_bin_label
from vibesensor.shared.constants import (
    SPEED_BIN_WIDTH_KMH,
    STEADY_SPEED_RANGE_KMH,
    STEADY_SPEED_STDDEV_KMH,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.use_cases.diagnostics._types import PhaseLabel, Sample
from vibesensor.use_cases.diagnostics.math_utils import (
    _mean_variance,
    _weighted_percentile,
)


def _amplitude_weighted_speed_window(
    speeds: list[float],
    amplitudes: list[float],
) -> tuple[float | None, float | None]:
    """Return the dominant amplitude-weighted speed bin window."""
    bin_weight: dict[str, float] = defaultdict(float)
    for speed, amp in zip(speeds, amplitudes, strict=False):
        speed_val = _as_float(speed)
        amp_val = _as_float(amp)
        if speed_val is None or speed_val <= 0 or amp_val is None or amp_val <= 0:
            continue
        bin_weight[speed_bin_label(speed_val)] += amp_val

    if not bin_weight:
        return (None, None)

    strongest_bin = max(
        bin_weight.items(),
        key=lambda item: (item[1], speed_band_sort_key(item[0])),
    )[0]
    low_kmh = float(speed_band_sort_key(strongest_bin))
    return (low_kmh, low_kmh + float(SPEED_BIN_WIDTH_KMH))


def _speed_stats(speed_values: list[float]) -> SpeedProfileSummary:
    if not speed_values:
        return SpeedProfileSummary()
    vmin = min(speed_values)
    vmax = max(speed_values)
    vmean, var = _mean_variance(speed_values)
    stddev = sqrt(var) if var is not None else 0.0
    vrange = max(0.0, vmax - vmin)
    return SpeedProfileSummary(
        min_kmh=vmin,
        max_kmh=vmax,
        mean_kmh=vmean,
        stddev_kmh=stddev,
        range_kmh=vrange,
        steady_speed=stddev < STEADY_SPEED_STDDEV_KMH and vrange < STEADY_SPEED_RANGE_KMH,
    )


def _speed_stats_by_phase(
    samples: list[Sample],
    per_sample_phases: Sequence[PhaseLabel],
) -> dict[str, SpeedProfileSummary]:
    """Compute speed statistics broken down by driving phase."""
    phase_speeds: dict[str, list[float]] = defaultdict(list)
    phase_sample_counts: dict[str, int] = defaultdict(int)
    for sample, phase in zip(samples, per_sample_phases, strict=True):
        phase_key = str(phase)
        phase_sample_counts[phase_key] += 1
        speed = _as_float(sample.get("speed_kmh"))
        if speed is not None and speed > 0:
            phase_speeds[phase_key].append(speed)
    result: dict[str, SpeedProfileSummary] = {}
    for phase_key in phase_sample_counts:
        base = _speed_stats(phase_speeds.get(phase_key, []))
        result[phase_key] = SpeedProfileSummary(
            min_kmh=base.min_kmh,
            max_kmh=base.max_kmh,
            mean_kmh=base.mean_kmh,
            stddev_kmh=base.stddev_kmh,
            range_kmh=base.range_kmh,
            steady_speed=base.steady_speed,
            sample_count=phase_sample_counts[phase_key],
        )
    return result


_SENTINEL = object()


def _phase_to_str(phase: object) -> str | None:
    """Return the string value for a phase object (DrivingPhase or str)."""
    if phase is None:
        return None
    val = getattr(phase, "value", _SENTINEL)
    if val is _SENTINEL:
        return str(phase)
    return str(val)


def _speed_profile_from_points(
    points: list[tuple[float, float]],
    *,
    allowed_speed_bins: list[str] | tuple[str, ...] | set[str] | None = None,
    phase_weights: list[float] | None = None,
) -> tuple[float | None, tuple[float, float] | None, str | None]:
    allowed = set(allowed_speed_bins) if allowed_speed_bins is not None else None

    _bin_label = speed_bin_label
    _float_or_none = _as_float

    valid: list[tuple[float, float]] = []
    effective_amps: list[float] = []
    speeds: list[float] = []
    phase_weights_seq = phase_weights if phase_weights is not None else []
    has_weights = phase_weights is not None
    n_weights = len(phase_weights_seq)

    for idx, (speed, amp) in enumerate(points):
        if speed <= 0 or amp <= 0:
            continue
        if allowed is not None and _bin_label(speed) not in allowed:
            continue
        phase_weight = 1.0
        if has_weights and idx < n_weights:
            parsed_weight = _float_or_none(phase_weights_seq[idx])
            if parsed_weight is not None and parsed_weight > 0:
                phase_weight = parsed_weight
        valid.append((speed, amp))
        effective_amps.append(amp * phase_weight)
        speeds.append(speed)

    if not valid:
        return None, None, None

    peak_speed_kmh = max(valid, key=lambda item: item[1])[0]
    low = _weighted_percentile(valid, 0.10)
    high = _weighted_percentile(valid, 0.90)
    if low is None or high is None:
        return peak_speed_kmh, None, None
    if high < low:
        low, high = high, low
    speed_window_kmh = (low, high)

    low_speed, high_speed = _amplitude_weighted_speed_window(
        speeds,
        effective_amps,
    )
    strongest_speed_band = (
        f"{low_speed:.0f}-{high_speed:.0f} km/h"
        if low_speed is not None and high_speed is not None
        else None
    )
    return peak_speed_kmh, speed_window_kmh, strongest_speed_band
