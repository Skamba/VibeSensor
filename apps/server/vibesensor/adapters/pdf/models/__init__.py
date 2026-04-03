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
from .document import Report, ReportTemplateData, build_report_from_renderer_payload
from .panels import DataTrustItem, NextStep, PartSuggestion, PatternEvidence, SystemFindingCard
from .sections import (
    FindingPresentation,
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
    "FindingPresentation",
    "MeasurementRow",
    "NextStep",
    "PartSuggestion",
    "PatternEvidence",
    "PeakRow",
    "RankedCandidateRow",
    "Report",
    "ReportLabelValueRow",
    "ReportTemplateData",
    "SensorObservationCell",
    "SensorObservationMatrixRow",
    "SystemFindingCard",
    "TimelineGraphData",
    "TimelineGraphInterval",
    "TopologyIntensityRow",
    "VerdictPageData",
    "build_report_from_renderer_payload",
]
