"""Canonical prepared report boundary shared by history and PDF mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from vibesensor.shared.boundaries.reporting.summary_codec import report_summary_from_mapping

if TYPE_CHECKING:
    from vibesensor.domain import (
        LocationHotspotRow,
        LocationIntensitySummary,
        RecommendedAction,
        SuitabilityCheck,
        TestRun,
        VibrationOrigin,
    )
    from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
    from vibesensor.shared.boundaries.reporting.summary_codec import ReportTimelineInterval
    from vibesensor.shared.run_context_warning import RunContextWarning
    from vibesensor.shared.types.analysis_views import PeakTableRow
    from vibesensor.shared.types.report_cache import ReportPdfCacheKey

ActionStatusKey = Literal["recapture_before_acting", "action_ready_caution", "action_ready"]
LocationConfidenceKey = Literal["weak", "mixed", "strong"]

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "PreparedAppendixADisplay",
    "PreparedAppendixBSummaryDisplay",
    "PreparedRankedCandidateDisplay",
    "PreparedReportDisplayFacts",
    "PreparedReportFacts",
    "PreparedReportInput",
    "PreparedReportRendererPayload",
    "PreparedVerdictDisplay",
    "ReportCoverageSummary",
    "build_report_renderer_payload",
]


@dataclass(frozen=True, slots=True)
class PreparedReportRendererPayload:
    """Minimal renderer-edge payload prepared from summary or persisted analysis."""

    run_id: str
    car_name: str | None
    car_type: str | None
    report_date: str | None
    duration_s: float | None
    sample_count: int
    sensor_count: int
    peak_table_rows: tuple[PeakTableRow, ...]
    recorded_utc_offset_seconds: int | None = None


def build_report_renderer_payload(
    payload: Mapping[str, object],
) -> PreparedReportRendererPayload:
    """Return the normalized renderer-edge payload derived from a report summary."""
    summary = report_summary_from_mapping(payload)
    typed_metadata = summary.metadata
    return PreparedReportRendererPayload(
        run_id=summary.run_id,
        car_name=typed_metadata.car_name if typed_metadata is not None else None,
        car_type=typed_metadata.car_type if typed_metadata is not None else None,
        report_date=summary.report_date,
        duration_s=summary.duration_s,
        sample_count=summary.sample_count,
        sensor_count=summary.sensor_count,
        peak_table_rows=summary.peak_table_rows,
        recorded_utc_offset_seconds=(
            typed_metadata.recorded_utc_offset_seconds if typed_metadata is not None else None
        ),
    )


@dataclass(frozen=True, slots=True)
class ReportCoverageSummary:
    """Coverage facts used by report preparation and rendering."""

    expected_locations: tuple[str, ...]
    active_locations: tuple[str, ...]
    missing_locations: tuple[str, ...]
    partial_locations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedRankedCandidateDisplay:
    source_name: str
    confidence_pct: str | None
    inspect_first: str | None
    path_role: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class PreparedVerdictDisplay:
    speed_window_label: str | None
    suspected_source: str | None
    inspect_first: str | None
    action_status: str
    action_status_note: str | None
    reason_sentence: str | None
    dominant_corner: str | None
    runner_up_corner: str | None
    location_confidence: str
    coverage_label: str
    also_consider: str | None
    proof_caveat: str | None
    proof_panel_title: str
    footer_routes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedAppendixADisplay:
    mode: str
    primary_source: str | None
    alternative_source: str | None
    why_primary_first: str | None
    why_alternative_next: str | None
    next_if_clean: str | None
    ranked_candidates: tuple[PreparedRankedCandidateDisplay, ...]
    capture_issues: tuple[str, ...]
    capture_changes: tuple[str, ...]
    capture_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedAppendixBSummaryDisplay:
    dominant_corner: str | None
    runner_up_corner: str | None
    dominance_ratio_text: str
    location_confidence: str
    coverage_label: str
    coverage_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedReportDisplayFacts:
    verdict: PreparedVerdictDisplay
    appendix_a: PreparedAppendixADisplay
    appendix_b: PreparedAppendixBSummaryDisplay


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
    display: PreparedReportDisplayFacts


@dataclass(frozen=True, slots=True)
class PreparedReportInput:
    """Mapping-ready report handoff with one canonical internal shape."""

    renderer_payload: PreparedReportRendererPayload
    language: str
    filename: str
    domain_test_run: TestRun
    report_facts: PreparedReportFacts
    cache_key: ReportPdfCacheKey | None = None
