"""Intermediate data model for the diagnostic PDF report.

Holds the lightweight dataclasses used during report mapping and PDF
rendering. ``Report`` captures run-level metadata for the mapper, while
``ReportTemplateData`` and related dataclasses are consumed by the
Canvas-based renderer.
"""

from __future__ import annotations

__all__ = [
    "AppendixAData",
    "AppendixBData",
    "AppendixCData",
    "AppendixDData",
    "build_report_from_renderer_payload",
    "DataTrustItem",
    "EvidenceChainRow",
    "FindingPresentation",
    "MeasurementRow",
    "NextStep",
    "PartSuggestion",
    "PatternEvidence",
    "PeakRow",
    "Report",
    "ReportLabelValueRow",
    "ReportTemplateData",
    "RankedCandidateRow",
    "SystemFindingCard",
    "TimelineGraphData",
    "TimelineGraphInterval",
    "TopologyIntensityRow",
    "VerdictPageData",
]

from dataclasses import dataclass, field

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary
from vibesensor.shared.boundaries.report_renderer_payload import PreparedReportRendererPayload

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    """Run-level metadata carrier consumed by the report mapping pipeline."""

    run_id: str
    title: str = ""
    lang: str = "en"
    car_name: str | None = None
    car_type: str | None = None
    report_date: str | None = None
    duration_s: float | None = None
    sample_count: int = 0
    sensor_count: int = 0

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must be non-empty")
        if self.duration_s is not None and self.duration_s < 0:
            raise ValueError("duration_s must be non-negative")


@dataclass
class PartSuggestion:
    """A suggested replacement part associated with a diagnostic finding."""

    name: str = ""


@dataclass
class SystemFindingCard:
    """A per-system diagnostic finding card for the report, with location and parts."""

    system_name: str = ""
    status_label: str | None = None
    strongest_location: str | None = None
    pattern_summary: str | None = None
    parts: list[PartSuggestion] = field(default_factory=list)
    tone: str = "neutral"


@dataclass
class NextStep:
    """A recommended diagnostic next step and its supporting detail."""

    action: str = ""
    why: str | None = None
    confirm: str | None = None
    falsify: str | None = None
    eta: str | None = None


@dataclass
class DataTrustItem:
    """A single data-quality check result (pass/warn/fail with detail).

    ``state`` defaults to ``"warn"`` so that data quality items reconstructed
    from older persisted data (where the ``state`` key may be absent) are
    treated conservatively rather than silently marked as passing.
    """

    check: str = ""
    state: str = "warn"
    detail: str | None = None


@dataclass
class PatternEvidence:
    """Evidence summary for the dominant vibration pattern from post-analysis.

    This class also serves as the observed-signature block for the report
    template (the ``observed`` field on :class:`ReportTemplateData`).
    """

    primary_system: str | None = None
    matched_systems: list[str] = field(default_factory=list)
    strongest_location: str | None = None
    speed_band: str | None = None
    strength_label: str | None = None
    strength_peak_db: float | None = None
    certainty_label: str | None = None
    certainty_pct: str | None = None
    certainty_reason: str | None = None
    warning: str | None = None
    interpretation: str | None = None
    why_parts_text: str | None = None


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


@dataclass
class ReportLabelValueRow:
    """A simple label/value row used in appendix metadata blocks."""

    label: str = ""
    value: str = ""


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
    location_confidence: str | None = None
    coverage_label: str | None = None
    also_consider: str | None = None
    proof_summary: str | None = None
    proof_caveat: str | None = None
    proof_panel_title: str | None = None
    footer_routes: tuple[str, ...] = ()
    timeline_graph: TimelineGraphData | None = None


@dataclass
class RankedCandidateRow:
    """One ranked source row used in the worksheet appendix."""

    source_name: str = ""
    confidence_pct: str | None = None
    inspect_first: str | None = None
    path_role: str | None = None
    reason: str | None = None


@dataclass
class TopologyIntensityRow:
    """One topology/intensity row for the sensor-topology appendix."""

    location: str = ""
    p95_db: float | None = None
    coverage_state: str | None = None


@dataclass
class MeasurementRow:
    """One supporting-measurement row in the evidence appendix."""

    measurement_id: str = ""
    source_name: str = ""
    signal_label: str = ""
    frequency_hz: float | None = None
    peak_db: float | None = None
    strength_db: float | None = None
    speed_window: str | None = None
    dominant_location: str | None = None
    classification: str | None = None


@dataclass
class EvidenceChainRow:
    """One evidence-chain row tying a candidate to concrete measurements."""

    source_name: str = ""
    supporting_signal_label: str = ""
    measurement_refs: list[str] = field(default_factory=list)
    matched_evidence_window_count: int | None = None
    speed_window: str | None = None
    dominant_location: str | None = None
    ambiguity_note: str | None = None


@dataclass
class AppendixAData:
    """Technician worksheet or capture-guidance appendix data."""

    mode: str = "workflow"
    primary_source: str | None = None
    alternative_source: str | None = None
    why_primary_first: str | None = None
    why_alternative_next: str | None = None
    next_if_clean: str | None = None
    ranked_candidates: list[RankedCandidateRow] = field(default_factory=list)
    capture_issues: list[str] = field(default_factory=list)
    capture_changes: list[str] = field(default_factory=list)
    capture_conditions: list[str] = field(default_factory=list)


@dataclass
class AppendixBData:
    """Spatial-proof appendix content."""

    dominant_corner: str | None = None
    runner_up_corner: str | None = None
    dominance_ratio_text: str | None = None
    location_confidence: str | None = None
    coverage_label: str | None = None
    coverage_notes: list[str] = field(default_factory=list)
    intensity_rows: list[TopologyIntensityRow] = field(default_factory=list)


@dataclass
class AppendixCData:
    """Evidence appendix content."""

    evidence_chain_rows: list[EvidenceChainRow] = field(default_factory=list)
    measurement_rows: list[MeasurementRow] = field(default_factory=list)
    evidence_summary: str | None = None
    measurement_guide: str | None = None
    context_summary: str | None = None
    limits_summary: str | None = None
    speed_band_summary: str | None = None
    phase_summary: str | None = None
    observations: list[str] = field(default_factory=list)
    suitability_items: list[DataTrustItem] = field(default_factory=list)


@dataclass
class AppendixDData:
    """Traceability appendix content."""

    rows: list[ReportLabelValueRow] = field(default_factory=list)


@dataclass(frozen=True)
class FindingPresentation:
    """Presentation-ready snapshot of a domain Finding for the PDF renderer.

    All fields are pre-resolved strings/floats so that the rendering layer
    never needs to import or understand domain objects.
    """

    suspected_source: str = ""
    severity: str = ""
    strongest_location: str | None = None
    peak_classification: str = ""
    order: str = ""
    frequency_hz: float | None = None
    effective_confidence: float = 0.0


@dataclass
class ReportTemplateData:
    """All data needed to render a diagnostic PDF report."""

    title: str = ""
    run_datetime: str | None = None
    run_id: str | None = None
    duration_text: str | None = None
    start_time_utc: str | None = None
    end_time_utc: str | None = None
    sample_rate_hz: str | None = None
    tire_spec_text: str | None = None
    sample_count: int = 0
    sensor_count: int = 0
    sensor_locations: list[str] = field(default_factory=list)
    sensor_model: str | None = None
    firmware_version: str | None = None
    car_name: str | None = None
    car_type: str | None = None
    observed: PatternEvidence = field(default_factory=PatternEvidence)
    system_cards: list[SystemFindingCard] = field(default_factory=list)
    next_steps: list[NextStep] = field(default_factory=list)
    data_trust: list[DataTrustItem] = field(default_factory=list)
    pattern_evidence: PatternEvidence = field(default_factory=PatternEvidence)
    peak_rows: list[PeakRow] = field(default_factory=list)
    version_marker: str = ""
    lang: str = "en"
    certainty_tier_key: str = "A"

    # Rendering context — pre-computed during mapping so the report
    # renderer never needs to read raw samples or call analysis code.
    findings: list[FindingPresentation] = field(default_factory=list)
    top_causes: list[FindingPresentation] = field(default_factory=list)
    sensor_intensity_by_location: list[LocationIntensitySummary] = field(default_factory=list)
    location_hotspot_rows: list[LocationHotspotRow] = field(default_factory=list)
    verdict_page: VerdictPageData = field(default_factory=VerdictPageData)
    appendix_a: AppendixAData = field(default_factory=AppendixAData)
    appendix_b: AppendixBData = field(default_factory=AppendixBData)
    appendix_c: AppendixCData = field(default_factory=AppendixCData)
    appendix_d: AppendixDData = field(default_factory=AppendixDData)


def build_report_from_renderer_payload(
    renderer_payload: PreparedReportRendererPayload,
    *,
    language: str,
) -> Report:
    """Create a ``Report`` metadata object from the prepared renderer payload."""
    return Report(
        run_id=renderer_payload.run_id or "unknown",
        lang=language,
        car_name=renderer_payload.car_name,
        car_type=renderer_payload.car_type,
        report_date=renderer_payload.report_date,
        duration_s=renderer_payload.duration_s,
        sample_count=renderer_payload.sample_count,
        sensor_count=renderer_payload.sensor_count,
    )
