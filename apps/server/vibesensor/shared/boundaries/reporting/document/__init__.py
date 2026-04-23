"""Canonical PDF document models grouped by concern."""

from .appendices import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    EvidenceChainRow,
    MeasurementRow,
    ProofWindowRow,
    RankedCandidateRow,
    ReportLabelValueRow,
    SensorObservationCell,
    SensorObservationMatrixRow,
    TopologyIntensityRow,
)
from .document import Report, ReportDocument
from .panels import DataTrustItem, NextStep, PartSuggestion, PatternEvidence, SystemFindingCard
from .sections import (
    PeakRow,
    TimelineGraphData,
    TimelineGraphInterval,
    VerdictPageData,
)
from .validation import validate_report_document

__all__ = [
    "AppendixAData",
    "AppendixBData",
    "AppendixCData",
    "DataTrustItem",
    "EvidenceChainRow",
    "MeasurementRow",
    "NextStep",
    "PartSuggestion",
    "PatternEvidence",
    "PeakRow",
    "ProofWindowRow",
    "RankedCandidateRow",
    "Report",
    "ReportLabelValueRow",
    "ReportDocument",
    "SensorObservationCell",
    "SensorObservationMatrixRow",
    "SystemFindingCard",
    "TimelineGraphData",
    "TimelineGraphInterval",
    "TopologyIntensityRow",
    "validate_report_document",
    "VerdictPageData",
]
