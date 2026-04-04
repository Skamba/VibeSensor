"""Timeline graph builders for report document composition."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.document import (
    TimelineGraphData,
    TimelineGraphInterval,
)

__all__ = ["build_timeline_graph_data"]


def build_timeline_graph_data(
    report_facts: PreparedReportFacts,
    *,
    duration_s: float | None,
) -> TimelineGraphData | None:
    max_interval_end = max(
        (interval.end_t_s or 0.0 for interval in report_facts.run.timeline_intervals),
        default=0.0,
    )
    resolved_duration = max(float(duration_s or 0.0), max_interval_end)
    if resolved_duration <= 0:
        return None
    intervals: list[TimelineGraphInterval] = []
    max_speed = 0.0
    ordered_intervals = sorted(
        report_facts.run.timeline_intervals,
        key=lambda interval: (
            interval.start_t_s is None,
            interval.start_t_s or 0.0,
            interval.end_t_s or 0.0,
        ),
    )
    for interval in ordered_intervals:
        if interval.start_t_s is None or interval.end_t_s is None:
            continue
        start_t_s = max(0.0, interval.start_t_s)
        end_t_s = min(resolved_duration, interval.end_t_s)
        if end_t_s <= start_t_s:
            continue
        present_speeds = [
            speed for speed in (interval.speed_min_kmh, interval.speed_max_kmh) if speed is not None
        ]
        if present_speeds:
            max_speed = max(max_speed, *present_speeds)
        intervals.append(
            TimelineGraphInterval(
                phase_label=interval.phase,
                start_t_s=start_t_s,
                end_t_s=end_t_s,
                speed_min_kmh=interval.speed_min_kmh,
                speed_max_kmh=interval.speed_max_kmh,
                has_fault_evidence=interval.has_fault_evidence,
            ),
        )
    if not intervals:
        return None
    speed_ceiling_kmh = max(10.0, max_speed * 1.10 if max_speed > 0 else 10.0)
    return TimelineGraphData(
        duration_s=resolved_duration,
        speed_ceiling_kmh=speed_ceiling_kmh,
        intervals=tuple(intervals),
    )
