"""Driving-phase segmentation for diagnostic runs.

Classifies each sample in a run into one of:
  IDLE, ACCELERATION, CRUISE, DECELERATION, BRAKING, COAST_DOWN, SPEED_UNKNOWN

The speed slope comes from the run's speed readings on the time axis, so rows
from several sensors and a GPS/OBD speed staircase do not upset it. BRAKING is
deceleration too firm for a car coasting in gear (see ``BRAKING_MIN_DECEL_G``).

Phase information helps the findings engine decide which samples are
diagnostically meaningful and which should be down-weighted.

Samples where GPS speed is unavailable (``speed_kmh is None``) are initially
classified as ``SPEED_UNKNOWN``.  A post-classification interpolation step
re-assigns unknown-speed gaps that are surrounded by moving phases so that
GPS dropouts do not silently discard valid vibration data (issue #287).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from vibesensor.analysis._types import Sample
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.driving_segment import DrivingPhase, DrivingPhaseSegment

# Thresholds (tuneable)
_IDLE_SPEED_KMH = 3.0  # below this → IDLE
_ACCEL_THRESHOLD_KMH_S = 1.5  # positive speed derivative
_DECEL_THRESHOLD_KMH_S = -1.5  # negative speed derivative
_COAST_DOWN_MAX_KMH = 15.0  # deceleration below this speed → coast-down
# The speed slope is a least-squares fit over the speed readings within this
# many seconds of each reading, on the time axis rather than row by row: rows
# from several sensors share or interleave timestamps, and GPS/OBD speed
# arrives as a staircase that holds each reading for up to a second.
_SLOPE_HALF_WINDOW_S = 1.5
_SLOPE_MIN_POINTS = 3

# Braking (see "Braking" in docs/analysis_pipeline.md). Neither GPS nor OBD-II
# reports the brake pedal, so braking is told from coasting by how fast the car
# sheds speed. Rolling resistance, aerodynamic drag and engine drag in gear slow
# a car at about 0.05-0.1 g (0.15 g at most in a low gear at high revs); a stop
# on the brakes sheds 0.2-0.4 g. From 0.2 g (7.1 km/h per second), sustained,
# the car is on the brakes.
_STANDARD_GRAVITY_KMH_PER_S = 9.80665 * 3.6
BRAKING_MIN_DECEL_G = 0.2
_BRAKING_THRESHOLD_KMH_S = -BRAKING_MIN_DECEL_G * _STANDARD_GRAVITY_KMH_PER_S
# A braking spell must last one analysis spectrum (2.56 s at 800 Hz) to show
# in one, and a jump between two speed readings (a GPS glitch) is not braking:
# the slope fit smears a jump over less than this.
BRAKING_MIN_DURATION_S = 2.5
# Real braking lowers the speed reading again and again (a 1 Hz GPS fix at
# least twice in 2.5 s); a jump lowers it once.
_BRAKING_MIN_SPEED_DROPS = 2
# Readings of one braking spell lie this close together in time.
_BRAKING_MAX_GAP_S = 1.0


@dataclass(slots=True)
class PhaseSegment:
    """One contiguous segment of a driving phase."""

    phase: DrivingPhase
    start_idx: int
    end_idx: int  # inclusive
    start_t_s: float
    end_t_s: float
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    sample_count: int = 0


def _speed_series(samples: Sequence[Sample]) -> list[tuple[float, float]]:
    """The run's speed readings on the time axis: one ``(t_s, speed)`` per timestamp.

    Rows from several sensors at one timestamp read the same speed source; their
    mean stands for that moment.
    """
    by_time: dict[float, list[float]] = {}
    for sample in samples:
        if sample.t_s is None or sample.speed_kmh is None:
            continue
        if not (math.isfinite(sample.t_s) and math.isfinite(sample.speed_kmh)):
            continue
        by_time.setdefault(sample.t_s, []).append(sample.speed_kmh)
    return [(t_s, sum(speeds) / len(speeds)) for t_s, speeds in sorted(by_time.items())]


def speed_slopes_kmh_s(
    series: Sequence[tuple[float, float]],
    *,
    half_window_s: float = _SLOPE_HALF_WINDOW_S,
) -> list[float | None]:
    """Least-squares speed slope (km/h per second) around each reading of *series*.

    *series* is sorted by time. A reading with fewer than three readings, or
    less than one second of readings, around it has no slope.
    """
    slopes: list[float | None] = []
    lo = 0
    hi = 0
    n = len(series)
    for t_s, _speed in series:
        while series[lo][0] < t_s - half_window_s:
            lo += 1
        while hi < n and series[hi][0] <= t_s + half_window_s:
            hi += 1
        window = series[lo:hi]
        span = window[-1][0] - window[0][0]
        if len(window) < _SLOPE_MIN_POINTS or span < half_window_s * (2.0 / 3.0):
            slopes.append(None)
            continue
        mean_t = sum(t for t, _v in window) / len(window)
        mean_v = sum(v for _t, v in window) / len(window)
        var_t = sum((t - mean_t) ** 2 for t, _v in window)
        cov = sum((t - mean_t) * (v - mean_v) for t, v in window)
        slopes.append(cov / var_t if var_t > 0 else None)
    return slopes


def braking_intervals(
    series: Sequence[tuple[float, float]],
    slopes: Sequence[float | None],
) -> list[tuple[float, float]]:
    """Time spans ``(start_t_s, end_t_s)`` where the car was on the brakes.

    The speed falls at ``BRAKING_MIN_DECEL_G`` or more, above coast-down speed,
    for ``BRAKING_MIN_DURATION_S`` or more, the speed reading dropping again and
    again.
    """
    intervals: list[tuple[float, float]] = []
    run: list[tuple[float, float]] = []

    def close_run() -> None:
        if not run or run[-1][0] - run[0][0] < BRAKING_MIN_DURATION_S:
            return
        drops = 0
        last = run[0][1]
        for _t_s, speed in run[1:]:
            if speed < last:
                drops += 1
            if speed != last:
                last = speed
        if drops >= _BRAKING_MIN_SPEED_DROPS:
            intervals.append((run[0][0], run[-1][0]))

    for (t_s, speed), slope in zip(series, slopes, strict=True):
        braking = (
            slope is not None and slope <= _BRAKING_THRESHOLD_KMH_S and speed >= _COAST_DOWN_MAX_KMH
        )
        if braking and run and t_s - run[-1][0] > _BRAKING_MAX_GAP_S:
            close_run()
            run = []
        if braking:
            run.append((t_s, speed))
        elif run:
            close_run()
            run = []
    close_run()
    return intervals


def _segment_duration_s(segment: PhaseSegment) -> float:
    if not (math.isfinite(segment.start_t_s) and math.isfinite(segment.end_t_s)):
        return 0.0
    return max(0.0, segment.end_t_s - segment.start_t_s)


def classify_sample_phase(
    speed_kmh: float | None,
    speed_deriv_kmh_s: float | None,
    *,
    braking: bool = False,
) -> DrivingPhase:
    """Classify a single sample into a driving phase.

    *braking* says the sample lies in a braking spell (``braking_intervals``).
    """
    if speed_kmh is None:
        return DrivingPhase.SPEED_UNKNOWN
    if speed_kmh < _IDLE_SPEED_KMH:
        return DrivingPhase.IDLE
    if braking and speed_kmh >= _COAST_DOWN_MAX_KMH:
        return DrivingPhase.BRAKING

    if speed_deriv_kmh_s is not None:
        if speed_deriv_kmh_s > _ACCEL_THRESHOLD_KMH_S:
            return DrivingPhase.ACCELERATION
        if speed_deriv_kmh_s < _DECEL_THRESHOLD_KMH_S:
            if speed_kmh < _COAST_DOWN_MAX_KMH:
                return DrivingPhase.COAST_DOWN
            return DrivingPhase.DECELERATION

    return DrivingPhase.CRUISE


# ---------------------------------------------------------------------------
# SPEED_UNKNOWN interpolation
# ---------------------------------------------------------------------------

_MOVING_PHASES = frozenset(
    {
        DrivingPhase.ACCELERATION,
        DrivingPhase.CRUISE,
        DrivingPhase.DECELERATION,
        DrivingPhase.BRAKING,
        DrivingPhase.COAST_DOWN,
    },
)


def _interpolate_speed_unknown(phases: list[DrivingPhase]) -> None:
    """In-place interpolation of SPEED_UNKNOWN gaps.

    For each contiguous run of SPEED_UNKNOWN samples, look at the nearest
    non-SPEED_UNKNOWN neighbour on each side:
      * Both neighbours are moving phases → assign the gap to CRUISE (we
        know the vehicle was moving but lack derivative info).
      * Exactly one neighbour is a moving phase (gap at run start/end) →
        assign the gap to that neighbour's phase.
      * Neither side is a moving phase (run boundary, IDLE, or another
        SPEED_UNKNOWN block) → leave as SPEED_UNKNOWN so that
        ``diagnostic_sample_mask`` still *includes* these samples
        (IDLE is excluded; SPEED_UNKNOWN is kept per issue #287).
    """
    n = len(phases)
    i = 0
    while i < n:
        if phases[i] != DrivingPhase.SPEED_UNKNOWN:
            i += 1
            continue
        # Find extent of SPEED_UNKNOWN run
        j = i
        while j < n and phases[j] == DrivingPhase.SPEED_UNKNOWN:
            j += 1
        # j is now one past the end of the gap [i, j)

        left: DrivingPhase | None = phases[i - 1] if i > 0 else None
        right: DrivingPhase | None = phases[j] if j < n else None

        left_moving = left in _MOVING_PHASES
        right_moving = right in _MOVING_PHASES

        fill: DrivingPhase | None
        if left_moving and right_moving:
            fill = DrivingPhase.CRUISE
        elif left_moving:
            fill = left
        elif right_moving:
            fill = right
        else:
            # Neither side is a moving phase (run boundary, IDLE, or nested
            # SPEED_UNKNOWN) — leave as SPEED_UNKNOWN.
            i = j
            continue

        if fill is None:
            i = j
            continue

        phases[i:j] = [fill] * (j - i)
        i = j


def segment_run_phases(
    samples: Sequence[Sample],
) -> tuple[list[DrivingPhase], list[PhaseSegment]]:
    """Classify every sample into a driving phase and return contiguous segments.

    Returns
    -------
    per_sample_phases : list[DrivingPhase]
        One phase label per sample (same order/length as *samples*).
    segments : list[PhaseSegment]
        Contiguous segments of identical phase, sorted by time.

    """
    n = len(samples)
    if n == 0:
        return [], []

    speeds: list[float | None] = [sample.speed_kmh for sample in samples]
    times: list[float | None] = [sample.t_s for sample in samples]

    series = _speed_series(samples)
    slopes = speed_slopes_kmh_s(series)
    slope_at = {t_s: slope for (t_s, _speed), slope in zip(series, slopes, strict=True)}
    braking = braking_intervals(series, slopes)

    per_sample: list[DrivingPhase] = []
    for speed, t_s in zip(speeds, times, strict=True):
        slope = slope_at.get(t_s) if t_s is not None else None
        in_braking = t_s is not None and any(start <= t_s <= end for start, end in braking)
        per_sample.append(classify_sample_phase(speed, slope, braking=in_braking))

    # Interpolate SPEED_UNKNOWN gaps: if a contiguous block of SPEED_UNKNOWN
    # samples is surrounded on both sides by the same moving phase (anything
    # other than IDLE), assign them that phase.  If the surrounding phases
    # differ but are both non-IDLE, fall back to CRUISE (the vehicle was
    # moving but we don't know the derivative).  Gaps at the very start or
    # end of the run that border a moving phase are assigned that phase.
    _interpolate_speed_unknown(per_sample)

    # Build contiguous segments
    segments: list[PhaseSegment] = []
    seg_start = 0
    for i in range(1, n + 1):
        if i < n and per_sample[i] == per_sample[seg_start]:
            continue
        # End of segment [seg_start, i-1]
        seg_end = i - 1
        seg_speeds = [s for s in speeds[seg_start : seg_end + 1] if s is not None]
        seg_times = [t for t in times[seg_start : seg_end + 1] if t is not None]
        # When no time values are available in this segment, preserve
        # continuity only if the previous segment had a finite end timestamp;
        # otherwise leave the time bounds unknown.
        if seg_times:
            start_t = min(seg_times)
            end_t = max(seg_times)
        elif segments and math.isfinite(segments[-1].end_t_s):
            start_t = segments[-1].end_t_s
            end_t = start_t
        else:
            start_t = math.nan
            end_t = math.nan
        segments.append(
            PhaseSegment(
                phase=per_sample[seg_start],
                start_idx=seg_start,
                end_idx=seg_end,
                start_t_s=start_t,
                end_t_s=end_t,
                speed_min_kmh=min(seg_speeds) if seg_speeds else None,
                speed_max_kmh=max(seg_speeds) if seg_speeds else None,
                sample_count=seg_end - seg_start + 1,
            ),
        )
        seg_start = i

    return per_sample, segments


def phase_summary(segments: list[PhaseSegment]) -> DrivingPhaseSummary:
    """Return a typed snapshot suitable for embedding in the run summary."""
    phase_counts: dict[str, int] = {}
    phase_durations: dict[str, float] = {}
    phase_speed_mins: dict[str, float] = {}
    phase_speed_maxs: dict[str, float] = {}
    total = 0
    for seg in segments:
        key = seg.phase.value
        phase_counts[key] = phase_counts.get(key, 0) + seg.sample_count
        total += seg.sample_count
        dur = _segment_duration_s(seg)
        phase_durations[key] = phase_durations.get(key, 0.0) + dur
        # Track speed range
        if seg.speed_min_kmh is not None:
            phase_speed_mins[key] = min(phase_speed_mins.get(key, float("inf")), seg.speed_min_kmh)
        if seg.speed_max_kmh is not None:
            phase_speed_maxs[key] = max(phase_speed_maxs.get(key, float("-inf")), seg.speed_max_kmh)

    phase_pcts: dict[str, float] = {}
    for phase, count in phase_counts.items():
        phase_pcts[phase] = (count / total * 100.0) if total > 0 else 0.0

    # Build DrivingPhaseSegment per phase type
    phase_type_summaries: list[DrivingPhaseSegment] = []
    for key, count in phase_counts.items():
        try:
            phase_enum = DrivingPhase(key)
        except ValueError:
            continue
        phase_type_summaries.append(
            DrivingPhaseSegment(
                phase=phase_enum,
                duration_s=phase_durations.get(key, 0.0),
                sample_count=count,
                speed_min_kmh=phase_speed_mins.get(key),
                speed_max_kmh=phase_speed_maxs.get(key),
                fraction=(count / total) if total > 0 else 0.0,
            ),
        )

    return DrivingPhaseSummary(
        phase_counts=phase_counts,
        phase_pcts=phase_pcts,
        total_samples=total,
        segment_count=len(segments),
        has_cruise=phase_counts.get(DrivingPhase.CRUISE.value, 0) > 0,
        has_acceleration=phase_counts.get(DrivingPhase.ACCELERATION.value, 0) > 0,
        cruise_pct=phase_pcts.get(DrivingPhase.CRUISE.value, 0.0),
        idle_pct=phase_pcts.get(DrivingPhase.IDLE.value, 0.0),
        speed_unknown_pct=phase_pcts.get(DrivingPhase.SPEED_UNKNOWN.value, 0.0),
        phase_type_summaries=tuple(phase_type_summaries),
    )


def diagnostic_sample_mask(per_sample_phases: list[DrivingPhase]) -> list[bool]:
    """Return which samples are diagnostically useful: every sample except IDLE.

    IDLE samples are engine-off / stationary noise. SPEED_UNKNOWN samples are
    *included* so that GPS dropouts do not silently discard valid vibration data
    (issue #287).
    """
    return [phase is not DrivingPhase.IDLE for phase in per_sample_phases]
