"""Canonical prepared report boundary shared by history and PDF mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from vibesensor.domain import (
        LocationHotspotRow,
        LocationIntensitySummary,
        RecommendedAction,
        SuitabilityCheck,
        TestRun,
        VibrationOrigin,
    )
    from vibesensor.shared.boundaries.reporting.document import (
        AppendixAData,
        AppendixBData,
        VerdictPageData,
    )
    from vibesensor.shared.boundaries.reporting.payload import (
        NormalizedReportSummary,
        ReportTimelineInterval,
    )
    from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
    from vibesensor.shared.run_context_warning import RunContextWarning
    from vibesensor.shared.types.report_cache import ReportPdfCacheKey

ActionStatusKey = Literal["recapture_before_acting", "action_ready_caution", "action_ready"]
LocationConfidenceKey = Literal["weak", "mixed", "strong"]

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "PreparedReportFacts",
    "PreparedReportInput",
    "ReportCoverageSummary",
]


@dataclass(frozen=True, slots=True)
class ReportCoverageSummary:
    """Coverage facts used by report preparation and rendering."""

    expected_locations: tuple[str, ...]
    active_locations: tuple[str, ...]
    missing_locations: tuple[str, ...]
    partial_locations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedReportFacts:
    """Semantic report facts consumed by the PDF adapter."""

    origin: VibrationOrigin | None
    origin_location: str
    sensor_locations_active: tuple[str, ...]
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_model: str | None
    firmware_version: str | None
    active_sensor_intensity: tuple[LocationIntensitySummary, ...]
    location_hotspot_rows: tuple[LocationHotspotRow, ...]
    primary_candidate_facts: PrimaryReportFacts
    recommended_actions: tuple[RecommendedAction, ...]
    suitability_checks: tuple[SuitabilityCheck, ...]
    warnings: tuple[RunContextWarning, ...]
    coverage_summary: ReportCoverageSummary
    action_status_key: ActionStatusKey
    location_confidence_key: LocationConfidenceKey
    alternative_source: str | None
    alternative_source_visible: bool
    confidence_gap_to_alternative: float | None
    timeline_intervals: tuple[ReportTimelineInterval, ...]
    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData


@dataclass(frozen=True, slots=True)
class PreparedReportInput:
    """Mapping-ready report handoff with one canonical internal shape."""

    summary: NormalizedReportSummary
    language: str
    filename: str
    domain_test_run: TestRun
    report_facts: PreparedReportFacts
    cache_key: ReportPdfCacheKey | None = None
