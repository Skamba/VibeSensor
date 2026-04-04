"""Canonical reporting boundary package."""

from .decision_facts import ReportDecisionFacts
from .facts import (
    ActionStatusKey,
    LocationConfidenceKey,
    PreparedReportFacts,
    ReportRunFacts,
    prepare_report_facts,
)
from .input import PreparedReportInput
from .preparation import prepare_persisted_report_input, prepare_report_input
from .projection import (
    PrimaryReportFacts,
    normalize_origin_location,
    resolve_primary_report_facts,
    resolve_report_origin,
)
from .sensor_facts import ReportCoverageSummary, ReportSensorFacts, sensor_fallback_strength_db
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
    "ReportDecisionFacts",
    "ReportCoverageSummary",
    "ReportRunFacts",
    "ReportSensorFacts",
    "ReportTimelineInterval",
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
]
