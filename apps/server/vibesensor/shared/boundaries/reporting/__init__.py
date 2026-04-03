"""Canonical reporting boundary package."""

from .facts import (
    ActionStatusKey,
    LocationConfidenceKey,
    PreparedReportFacts,
    ReportCoverageSummary,
    prepare_report_facts,
)
from .input import PreparedReportInput
from .preparation import prepare_persisted_report_input, prepare_report_input
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
from .summary import (
    NormalizedReportSummary,
    ReportTimelineInterval,
    has_projectable_report_payload,
    report_summary_from_mapping,
    require_projectable_report_payload,
)

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "NormalizedReportSummary",
    "PreparedReportFacts",
    "PreparedReportInput",
    "PrimaryReportFacts",
    "ReportCoverageSummary",
    "ReportTimelineInterval",
    "collect_location_intensity",
    "compute_location_hotspot_rows",
    "filter_active_sensor_intensity",
    "has_projectable_report_payload",
    "normalize_origin_location",
    "prepare_persisted_report_input",
    "prepare_report_facts",
    "prepare_report_input",
    "report_summary_from_mapping",
    "require_projectable_report_payload",
    "resolve_primary_report_facts",
    "resolve_report_origin",
    "sensor_fallback_strength_db",
    "tire_spec_text",
]
