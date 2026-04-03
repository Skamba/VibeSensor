"""Canonical reporting boundary package."""

from .contracts import (
    ActionStatusKey,
    LocationConfidenceKey,
    PreparedAppendixADisplay,
    PreparedAppendixBSummaryDisplay,
    PreparedRankedCandidateDisplay,
    PreparedReportDisplayFacts,
    PreparedReportFacts,
    PreparedReportInput,
    PreparedVerdictDisplay,
    ReportCoverageSummary,
)
from .payload import (
    NormalizedReportSummary,
    ReportTimelineInterval,
    has_projectable_report_payload,
    report_summary_from_mapping,
    require_projectable_report_payload,
)
from .projection import (
    PrimaryReportFacts,
    collect_location_intensity,
    compute_location_hotspot_rows,
    filter_active_sensor_intensity,
    normalize_origin_location,
    resolve_primary_report_facts,
    resolve_report_origin,
    sensor_fallback_strength_db,
    tire_spec_text,
)

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "NormalizedReportSummary",
    "PreparedAppendixADisplay",
    "PreparedAppendixBSummaryDisplay",
    "PreparedRankedCandidateDisplay",
    "PreparedReportDisplayFacts",
    "PreparedReportFacts",
    "PreparedReportInput",
    "PreparedVerdictDisplay",
    "PrimaryReportFacts",
    "ReportCoverageSummary",
    "ReportTimelineInterval",
    "collect_location_intensity",
    "compute_location_hotspot_rows",
    "filter_active_sensor_intensity",
    "has_projectable_report_payload",
    "normalize_origin_location",
    "report_summary_from_mapping",
    "require_projectable_report_payload",
    "resolve_primary_report_facts",
    "resolve_report_origin",
    "sensor_fallback_strength_db",
    "tire_spec_text",
]
