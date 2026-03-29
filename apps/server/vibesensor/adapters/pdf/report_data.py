"""Intermediate data model for the diagnostic PDF report.

Holds the lightweight dataclasses used during report mapping and PDF
rendering. ``Report`` captures run-level metadata for the mapper, while
``ReportTemplateData`` and related dataclasses are consumed by the
Canvas-based renderer.
"""

from __future__ import annotations

__all__ = [
    "build_report_from_renderer_payload",
    "DataTrustItem",
    "FindingPresentation",
    "NextStep",
    "PartSuggestion",
    "PatternEvidence",
    "PeakRow",
    "Report",
    "ReportTemplateData",
    "SystemFindingCard",
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
