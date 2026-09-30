"""Canonical reporting boundary package."""

# Summary normalization and projectable-payload gates.
# Fact projections and prepared fact groups.
from .analysis_metadata import (
    REPORT_ANALYSIS_METADATA_STABLE_KEYS,
    ReportAnalysisMetadata,
    report_analysis_metadata_from_mapping,
)
from .confidence_facts import ReportConfidenceFacts, build_report_confidence_facts
from .decision_facts import ReportDecisionFacts, build_report_decision_facts
from .facts import (
    ActionStatusKey,
    LocationConfidenceKey,
    PreparedReportFacts,
    ReportContextFacts,
    ReportRunFacts,
    prepare_report_facts,
)
from .fallback_reasons import (
    REPORT_FALLBACK_REASON_VALUES,
    REPORT_FALLBACK_REASONS_METADATA_KEY,
    ReportFallbackReason,
)
from .input import PreparedReportInput, validate_prepared_report_input

# Reconstructed prepared-input entrypoints.
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
    "build_report_decision_facts",
    "build_report_confidence_facts",
    "LocationConfidenceKey",
    "NormalizedReportSummary",
    "PreparedReportFacts",
    "PreparedReportInput",
    "PrimaryReportFacts",
    "REPORT_ANALYSIS_METADATA_STABLE_KEYS",
    "REPORT_FALLBACK_REASONS_METADATA_KEY",
    "REPORT_FALLBACK_REASON_VALUES",
    "ReportAnalysisMetadata",
    "ReportConfidenceFacts",
    "ReportContextFacts",
    "ReportCoverageSummary",
    "ReportDecisionFacts",
    "ReportFallbackReason",
    "ReportRunFacts",
    "ReportSensorFacts",
    "ReportTimelineInterval",
    "has_projectable_report_payload",
    "normalize_origin_location",
    "prepare_persisted_report_input",
    "prepare_report_facts",
    "prepare_report_input",
    "report_analysis_metadata_from_mapping",
    "report_summary_from_mapping",
    "require_projectable_report_payload",
    "resolve_primary_report_facts",
    "resolve_report_origin",
    "sensor_fallback_strength_db",
    "validate_prepared_report_input",
]
