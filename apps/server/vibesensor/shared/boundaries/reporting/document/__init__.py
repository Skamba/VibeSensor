"""Canonical PDF document models grouped by concern."""

from .appendices import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    DenseEvidenceRow,
    EvidenceChainRow,
    MeasurementRow,
    ProofWindowRow,
    RankedCandidateRow,
    ReportLabelValueRow,
    SensorObservationCell,
    SensorObservationMatrixRow,
    TopologyIntensityRow,
)
from .document import ReportDocument
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
    "DenseEvidenceRow",
    "EvidenceChainRow",
    "MeasurementRow",
    "NextStep",
    "PartSuggestion",
    "PatternEvidence",
    "PeakRow",
    "ProofWindowRow",
    "RankedCandidateRow",
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
