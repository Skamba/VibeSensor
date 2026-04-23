"""Driving-phase segmentation for diagnostic runs.

Classifies each sample in a run into one of:
  IDLE, ACCELERATION, CRUISE, DECELERATION, COAST_DOWN, SPEED_UNKNOWN

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
from dataclasses import dataclass, replace

from vibesensor.domain import DrivingPhase, speed_band_sort_key
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.driving_segment import DrivingPhaseSegment
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunContextInterval,
    WholeRunContextLoadState,
    WholeRunContextWindowLabel,
)
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.use_cases.diagnostics.whole_run_windows import WholeRunWindowPlan

# Thresholds (tuneable)
_IDLE_SPEED_KMH = 3.0  # below this → IDLE
_ACCEL_THRESHOLD_KMH_S = 1.5  # positive speed derivative
_DECEL_THRESHOLD_KMH_S = -1.5  # negative speed derivative
_COAST_DOWN_MAX_KMH = 15.0  # deceleration below this speed → coast-down


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


@dataclass(frozen=True, slots=True)
class WholeRunPhaseSegmentation:
    """Whole-run phase segmentation result over normalized window context."""

    labels: tuple[WholeRunContextWindowLabel, ...]
    intervals: tuple[WholeRunContextInterval, ...]


def _find_nearest_valid(
    speeds: list[float | None],
    times: list[float | None],
    rng: range,
) -> tuple[float | None, float | None]:
    """Return the first (speed, time) pair where both are non-None in *rng*."""
    for j in rng:
        if speeds[j] is not None and times[j] is not None:
            return speeds[j], times[j]
    return None, None


def _estimate_speed_derivative(
    speeds: list[float | None],
    times: list[float | None],
    idx: int,
    *,
    window: int = 2,
) -> float | None:
    """Central-difference speed derivative (km/h per second) at *idx*."""
    n = len(speeds)
    if idx < 0 or idx >= n:
        return None
    # Look backward and forward for valid speed+time pairs
    prev_speed, prev_time = _find_nearest_valid(
        speeds,
        times,
        range(idx - 1, max(-1, idx - window - 1), -1),
    )
    next_speed, next_time = _find_nearest_valid(
        speeds,
        times,
        range(idx + 1, min(n, idx + window + 1)),
    )

    if (
        prev_speed is not None
        and prev_time is not None
        and next_speed is not None
        and next_time is not None
    ):
        dt = next_time - prev_time
        if dt > 0.01:
            return (next_speed - prev_speed) / dt

    # Fallback: one-sided derivative
    cur_speed = speeds[idx]
    cur_time = times[idx]
    if cur_speed is None or cur_time is None:
        return None
    if prev_speed is not None and prev_time is not None:
        dt = cur_time - prev_time
        if dt > 0.01:
            return (cur_speed - prev_speed) / dt
    if next_speed is not None and next_time is not None:
        dt = next_time - cur_time
        if dt > 0.01:
            return (next_speed - cur_speed) / dt
    return None


def _segment_duration_s(segment: PhaseSegment) -> float:
    if not (math.isfinite(segment.start_t_s) and math.isfinite(segment.end_t_s)):
        return 0.0
    return max(0.0, segment.end_t_s - segment.start_t_s)


def classify_sample_phase(
    speed_kmh: float | None,
    speed_deriv_kmh_s: float | None,
) -> DrivingPhase:
    """Classify a single sample into a driving phase."""
    if speed_kmh is None:
        return DrivingPhase.SPEED_UNKNOWN
    if speed_kmh < _IDLE_SPEED_KMH:
        return DrivingPhase.IDLE

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

    # Extract speeds and times (preserve order)
    speeds: list[float | None] = [sample.speed_kmh for sample in samples]
    times: list[float | None] = [sample.t_s for sample in samples]

    # Classify each sample
    per_sample: list[DrivingPhase] = []
    for i in range(n):
        deriv = _estimate_speed_derivative(speeds, times, i)
        phase = classify_sample_phase(speeds[i], deriv)
        per_sample.append(phase)

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


def segment_whole_run_context(
    *,
    labels: Sequence[WholeRunContextWindowLabel],
    window_plan: WholeRunWindowPlan,
) -> WholeRunPhaseSegmentation:
    """Segment normalized whole-run labels into deterministic phase intervals."""

    if not labels:
        return WholeRunPhaseSegmentation(labels=(), intervals=())
    windows = window_plan.windows
    if len(labels) != len(windows):
        raise ValueError("whole-run phase segmentation requires one label per planned window")
    for label, window in zip(labels, windows, strict=True):
        if label.window_index != window.window_index:
            raise ValueError("whole-run phase segmentation requires labels ordered by window_index")

    speeds: list[float | None] = [
        label.speed_kmh
        if (
            label.speed_kmh is not None
            and not label.speed_is_stale
            and label.speed_validity != "missing"
        )
        else None
        for label in labels
    ]
    times: list[float | None] = [window.center_t_s for window in windows]
    per_window_phases: list[DrivingPhase] = []
    for index in range(len(labels)):
        deriv = _estimate_speed_derivative(speeds, times, index)
        per_window_phases.append(classify_sample_phase(speeds[index], deriv))
    _interpolate_speed_unknown(per_window_phases)

    intervals: list[WholeRunContextInterval] = []
    updated_labels: list[WholeRunContextWindowLabel] = []
    segment_start = 0
    for index in range(1, len(per_window_phases) + 1):
        if (
            index < len(per_window_phases)
            and per_window_phases[index] == per_window_phases[segment_start]
        ):
            continue
        segment_end = index - 1
        phase = per_window_phases[segment_start]
        interval = _build_whole_run_context_interval(
            segment_index=len(intervals),
            phase=phase,
            labels=labels[segment_start : segment_end + 1],
            windows=windows[segment_start : segment_end + 1],
        )
        intervals.append(interval)
        load_state = _load_state_from_phase(phase)
        for label_index in range(segment_start, segment_end + 1):
            updated_labels.append(
                replace(
                    labels[label_index],
                    phase=phase,
                    load_state=load_state,
                    segment_index=interval.segment_index,
                )
            )
        segment_start = index

    return WholeRunPhaseSegmentation(labels=tuple(updated_labels), intervals=tuple(intervals))


def _build_whole_run_context_interval(
    *,
    segment_index: int,
    phase: DrivingPhase,
    labels: Sequence[WholeRunContextWindowLabel],
    windows: Sequence,
) -> WholeRunContextInterval:
    fresh_speeds = [
        label.speed_kmh
        for label in labels
        if (
            label.speed_kmh is not None
            and not label.speed_is_stale
            and label.speed_validity != "missing"
        )
    ]
    coverage_counts = {
        "full": sum(1 for label in labels if label.context_coverage == "full"),
        "partial": sum(1 for label in labels if label.context_coverage == "partial"),
        "missing": sum(1 for label in labels if label.context_coverage == "missing"),
    }
    return WholeRunContextInterval(
        segment_index=segment_index,
        phase=phase,
        load_state=_load_state_from_phase(phase),
        start_window_index=windows[0].window_index,
        end_window_index=windows[-1].window_index,
        start_t_s=windows[0].start_t_s,
        end_t_s=windows[-1].end_t_s,
        speed_min_kmh=min(fresh_speeds) if fresh_speeds else None,
        speed_max_kmh=max(fresh_speeds) if fresh_speeds else None,
        speed_band=_dominant_speed_band(labels),
        full_context_window_count=coverage_counts["full"],
        partial_context_window_count=coverage_counts["partial"],
        missing_context_window_count=coverage_counts["missing"],
    )


def _dominant_speed_band(labels: Sequence[WholeRunContextWindowLabel]) -> str | None:
    band_counts: dict[str, int] = {}
    for label in labels:
        if label.speed_band is None or label.speed_is_stale:
            continue
        band_counts[label.speed_band] = band_counts.get(label.speed_band, 0) + 1
    if not band_counts:
        return None
    return max(
        band_counts.items(),
        key=lambda item: (item[1], speed_band_sort_key(item[0])),
    )[0]


def _load_state_from_phase(phase: DrivingPhase) -> WholeRunContextLoadState:
    if phase is DrivingPhase.IDLE:
        return "idle"
    if phase in {
        DrivingPhase.ACCELERATION,
        DrivingPhase.DECELERATION,
        DrivingPhase.COAST_DOWN,
    }:
        return "transient"
    if phase is DrivingPhase.CRUISE:
        return "steady"
    return "unknown"


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


def diagnostic_sample_mask(
    per_sample_phases: list[DrivingPhase],
    *,
    exclude_idle: bool = True,
    exclude_coast_down: bool = False,
) -> list[bool]:
    """Return a boolean mask indicating which samples are diagnostically useful.

    By default excludes IDLE samples (engine-off / stationary noise).
    SPEED_UNKNOWN samples are always *included* so that GPS dropouts do not
    silently discard valid vibration data (issue #287).
    Coast-down can optionally be excluded when only powered driving is relevant.
    """
    excluded: set[DrivingPhase] = set()
    if exclude_idle:
        excluded.add(DrivingPhase.IDLE)
    if exclude_coast_down:
        excluded.add(DrivingPhase.COAST_DOWN)
    return [phase not in excluded for phase in per_sample_phases]
