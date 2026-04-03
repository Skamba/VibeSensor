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
    PreparedReportRendererPayload,
    PreparedVerdictDisplay,
    ReportCoverageSummary,
    build_report_renderer_payload,
)
from .payload_gate import has_projectable_report_payload
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
from .summary_codec import (
    NormalizedReportSummary,
    ReportTimelineInterval,
    report_summary_from_mapping,
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
    "PreparedReportRendererPayload",
    "PreparedVerdictDisplay",
    "PrimaryReportFacts",
    "ReportCoverageSummary",
    "ReportTimelineInterval",
    "build_report_renderer_payload",
    "collect_location_intensity",
    "compute_location_hotspot_rows",
    "filter_active_sensor_intensity",
    "has_projectable_report_payload",
    "normalize_origin_location",
    "report_summary_from_mapping",
    "resolve_primary_report_facts",
    "resolve_report_origin",
    "sensor_fallback_strength_db",
    "tire_spec_text",
]
