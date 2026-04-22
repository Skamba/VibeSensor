"""Top-level report document models for PDF rendering."""

from __future__ import annotations

from dataclasses import dataclass, field

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary

from ..findings import FindingPresentation
from .appendices import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    ReportLabelValueRow,
)
from .panels import DataTrustItem, NextStep, PatternEvidence, SystemFindingCard
from .sections import PeakRow, VerdictPageData

__all__ = [
    "Report",
    "ReportDocument",
]


@dataclass(frozen=True, slots=True)
class Report:
    """Run-level metadata carrier consumed by report assembly."""

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
class ReportDocument:
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
    lang: str = "en"
    certainty_tier_key: str = "A"
    findings: list[FindingPresentation] = field(default_factory=list)
    top_causes: list[FindingPresentation] = field(default_factory=list)
    sensor_intensity_by_location: list[LocationIntensitySummary] = field(default_factory=list)
    location_hotspot_rows: list[LocationHotspotRow] = field(default_factory=list)
    proof_sensor_intensity_by_location: list[LocationIntensitySummary] = field(default_factory=list)
    proof_location_hotspot_rows: list[LocationHotspotRow] = field(default_factory=list)
    verdict_page: VerdictPageData = field(default_factory=VerdictPageData)
    appendix_a: AppendixAData = field(default_factory=AppendixAData)
    appendix_b: AppendixBData = field(default_factory=AppendixBData)
    appendix_c: AppendixCData = field(default_factory=AppendixCData)
    traceability_rows: list[ReportLabelValueRow] = field(default_factory=list)
