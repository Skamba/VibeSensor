"""Canonical PDF document models grouped by concern."""

from .appendices import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    AppendixDData,
    EvidenceChainRow,
    MeasurementRow,
    RankedCandidateRow,
    ReportLabelValueRow,
    SensorObservationCell,
    SensorObservationMatrixRow,
    TopologyIntensityRow,
)
from .context import ReportDocumentContext
from .document import Report, ReportDocument
from .panels import DataTrustItem, NextStep, PartSuggestion, PatternEvidence, SystemFindingCard
from .sections import (
    PeakRow,
    TimelineGraphData,
    TimelineGraphInterval,
    VerdictPageData,
)

__all__ = [
    "AppendixAData",
    "AppendixBData",
    "AppendixCData",
    "AppendixDData",
    "DataTrustItem",
    "EvidenceChainRow",
    "MeasurementRow",
    "NextStep",
    "PartSuggestion",
    "PatternEvidence",
    "PeakRow",
    "RankedCandidateRow",
    "Report",
    "ReportDocumentContext",
    "ReportLabelValueRow",
    "ReportDocument",
    "SensorObservationCell",
    "SensorObservationMatrixRow",
    "SystemFindingCard",
    "TimelineGraphData",
    "TimelineGraphInterval",
    "TopologyIntensityRow",
    "VerdictPageData",
]
