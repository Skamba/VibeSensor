"""Section-level presentation models for PDF report assembly."""

from __future__ import annotations

from dataclasses import dataclass

from .appendices import ReportLabelValueRow

__all__ = [
    "PeakRow",
    "TimelineGraphData",
    "TimelineGraphInterval",
    "VerdictPageData",
]


@dataclass
class PeakRow:
    """A single row in the report's peak-frequency evidence table."""

    rank: str = ""
    system: str = ""
    freq_hz: str = ""
    order: str = ""
    peak_db: str = ""
    strength_db: str = ""
    speed_band: str = ""
    relevance: str = ""


@dataclass(frozen=True, slots=True)
class TimelineGraphInterval:
    """Presentation-ready interval for the page-1 run timeline graph."""

    phase_label: str
    start_t_s: float
    end_t_s: float
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    has_fault_evidence: bool = False

    def __post_init__(self) -> None:
        if self.end_t_s < self.start_t_s:
            raise ValueError("TimelineGraphInterval end_t_s must be >= start_t_s")


@dataclass(frozen=True, slots=True)
class TimelineGraphData:
    """Presentation-ready page-1 run timeline graph content."""

    duration_s: float
    speed_ceiling_kmh: float
    intervals: tuple[TimelineGraphInterval, ...] = ()

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("TimelineGraphData duration_s must be positive")
        if self.speed_ceiling_kmh <= 0:
            raise ValueError("TimelineGraphData speed_ceiling_kmh must be positive")


@dataclass
class VerdictPageData:
    """Presentation-ready page-1 decision surface content."""

    speed_window_label: str | None = None
    suspected_source: str | None = None
    inspect_first: str | None = None
    action_status: str | None = None
    action_status_note: str | None = None
    reason_sentence: str | None = None
    dominant_corner: str | None = None
    runner_up_corner: str | None = None
    dominance_ratio_label: str | None = None
    location_confidence: str | None = None
    coverage_label: str | None = None
    fallback_path: str | None = None
    also_consider: str | None = None
    proof_summary: str | None = None
    proof_caveat: str | None = None
    proof_panel_title: str | None = None
    proof_snapshot_rows: tuple[ReportLabelValueRow, ...] = ()
    footer_routes: tuple[str, ...] = ()
    timeline_graph: TimelineGraphData | None = None
