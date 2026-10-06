"""Speed-profile helper functions shared across diagnostics modules."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from math import sqrt

from vibesensor.analysis._types import PhaseLabel, Sample
from vibesensor.analysis.constants import (
    CONSTANT_SPEED_STDDEV_KMH,
    CONSTANT_SPEED_STDDEV_RAMP_KMH,
    SPEED_BIN_WIDTH_KMH,
    STEADY_SPEED_RANGE_KMH,
    STEADY_SPEED_RANGE_RAMP_KMH,
    STEADY_SPEED_STDDEV_KMH,
    STEADY_SPEED_STDDEV_RAMP_KMH,
)
from vibesensor.analysis.math_utils import _ramp, _weighted_percentile
from vibesensor.common.json_utils import as_float_or_none as _as_float
from vibesensor.domain.finding import speed_band_sort_key, speed_bin_label
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.dsp.statistics_utils import _mean_variance

# Fewer matched points than this in a speed bin say little about how hard it shakes there.
_MIN_POINTS_PER_BAND = 3
# A speed typed in by hand is not a measurement: every sample carries the set value.
_MANUAL_SPEED_SOURCES = frozenset({"manual", "fallback_manual"})


def speed_steadiness(stddev_kmh: float | None, range_kmh: float | None) -> float:
    """How steady the speed was, 0 to 1, for order confidence.

    1 within the steady-speed limits (stddev under 2 km/h and range under
    8 km/h), easing to 0 over the next 1 km/h of stddev and 4 km/h of range.
    """
    if stddev_kmh is None or range_kmh is None:
        return 0.0
    return min(
        1.0
        - _ramp(
            stddev_kmh,
            STEADY_SPEED_STDDEV_KMH,
            STEADY_SPEED_STDDEV_KMH + STEADY_SPEED_STDDEV_RAMP_KMH,
        ),
        1.0
        - _ramp(
            range_kmh,
            STEADY_SPEED_RANGE_KMH,
            STEADY_SPEED_RANGE_KMH + STEADY_SPEED_RANGE_RAMP_KMH,
        ),
    )


def speed_constancy(stddev_kmh: float | None) -> float:
    """How constant the speed was, 0 to 1: 1 under 0.5 km/h stddev, 0 from 1.0 km/h."""
    if stddev_kmh is None:
        return 0.0
    return 1.0 - _ramp(
        stddev_kmh,
        CONSTANT_SPEED_STDDEV_KMH,
        CONSTANT_SPEED_STDDEV_KMH + CONSTANT_SPEED_STDDEV_RAMP_KMH,
    )


def run_speed_source(samples: Sequence[Sample]) -> str | None:
    """The most common speed source among the moving samples."""
    counts = Counter(
        sample.speed_source.strip().lower()
        for sample in samples
        if sample.speed_kmh is not None and sample.speed_kmh > 0 and sample.speed_source.strip()
    )
    return counts.most_common(1)[0][0] if counts else None


def speed_typed_in(speed_source: str | None) -> bool:
    """The run speed was entered by hand, not measured live (GPS/OBD-II)."""
    return speed_source in _MANUAL_SPEED_SOURCES


def _amplitude_weighted_speed_window(
    speeds: Sequence[float],
    amplitudes: Sequence[float],
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


def _loudest_speed_window(
    speeds: Sequence[float],
    amplitudes: Sequence[float],
    weights: Sequence[float],
) -> tuple[float | None, float | None]:
    """The speed bin where the weighted mean amplitude is highest.

    A mean, not a sum: lingering at one speed (a cruise, a long hold) does not
    make a vibration strongest there; where it shakes hardest does. A bin with
    fewer than ``_MIN_POINTS_PER_BAND`` points counts only when no bin has more.
    """
    total: dict[str, float] = defaultdict(float)
    weight: dict[str, float] = defaultdict(float)
    count: Counter[str] = Counter()
    for speed, amp, point_weight in zip(speeds, amplitudes, weights, strict=True):
        label = speed_bin_label(speed)
        total[label] += amp * point_weight
        weight[label] += point_weight
        count[label] += 1
    if not total:
        return (None, None)
    eligible = [label for label in total if count[label] >= _MIN_POINTS_PER_BAND] or list(total)
    strongest_bin = max(
        eligible,
        key=lambda label: (total[label] / weight[label], speed_band_sort_key(label)),
    )
    low_kmh = float(speed_band_sort_key(strongest_bin))
    return (low_kmh, low_kmh + float(SPEED_BIN_WIDTH_KMH))


def _speed_stats(speed_values: Sequence[float]) -> SpeedProfileSummary:
    if not speed_values:
        return SpeedProfileSummary()
    vmin = min(speed_values)
    vmax = max(speed_values)
    vmean, var = _mean_variance(list(speed_values))
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
    samples: Sequence[Sample],
    per_sample_phases: Sequence[PhaseLabel],
) -> dict[str, SpeedProfileSummary]:
    """Compute speed statistics broken down by driving phase."""
    phase_speeds: dict[str, list[float]] = defaultdict(list)
    phase_sample_counts: dict[str, int] = defaultdict(int)
    for sample, phase in zip(samples, per_sample_phases, strict=True):
        phase_key = str(phase)
        phase_sample_counts[phase_key] += 1
        speed = sample.speed_kmh
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
    points: Sequence[tuple[float, float]],
    *,
    allowed_speed_bins: Sequence[str] | set[str] | None = None,
    phase_weights: Sequence[float] | None = None,
) -> tuple[float | None, tuple[float, float] | None, str | None]:
    allowed = set(allowed_speed_bins) if allowed_speed_bins is not None else None

    _bin_label = speed_bin_label
    _float_or_none = _as_float

    valid: list[tuple[float, float]] = []
    weights: list[float] = []
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
        weights.append(phase_weight)
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

    low_speed, high_speed = _loudest_speed_window(
        speeds,
        [amp for _speed, amp in valid],
        weights,
    )
    strongest_speed_band = (
        f"{low_speed:.0f}-{high_speed:.0f} km/h"
        if low_speed is not None and high_speed is not None
        else None
    )
    return peak_speed_kmh, speed_window_kmh, strongest_speed_band
