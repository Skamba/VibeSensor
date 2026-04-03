"""Semantic prepared reporting facts shared across presentation and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from vibesensor.domain import (
        LocationHotspotRow,
        LocationIntensitySummary,
        RecommendedAction,
        SuitabilityCheck,
        VibrationOrigin,
    )
    from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
    from vibesensor.shared.boundaries.reporting.summary import ReportTimelineInterval
    from vibesensor.shared.run_context_warning import RunContextWarning

ActionStatusKey = Literal["recapture_before_acting", "action_ready_caution", "action_ready"]
LocationConfidenceKey = Literal["weak", "mixed", "strong"]

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "PreparedReportFacts",
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
    """Semantic report facts independent from presentation-specific sections."""

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
