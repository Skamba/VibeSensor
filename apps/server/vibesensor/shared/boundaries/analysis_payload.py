"""Boundary serialization types for analysis payloads.

These aliases define the wire/persistence shapes for analysis data that
crosses the domain-adapter boundary. Stable exact history/view shapes shared
with the HTTP layer live in ``shared.types.analysis_views``. Shared
analysis/history wrapper and composite owners live in
``shared.types.history_analysis_contracts`` and should be imported directly
from there when the same contract spans boundary, persistence, and HTTP flows.
This module only carries payload-oriented aliases for supporting leaf shapes.
"""

from __future__ import annotations

from vibesensor.shared.types.analysis_views import (
    AmpVsPhaseRow,
    FindingEvidenceMetrics,
    FreqVsSpeedByFindingSeries,
    LocationHotspotPayload,
    MatchedAmpVsSpeedSeries,
    MatchedPoint,
    PeakTableRow,
    PhaseBoundary,
    PhaseEvidence,
    PhaseSegmentOut,
    PhaseSpeedBreakdownRow,
    PlotDataResult,
    SpectrogramResult,
    SpeedBreakdownRow,
)
from vibesensor.shared.types.history_analysis_contracts import (
    AmplitudeMetric,
    RunSuitabilityCheck,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualityAccelSanityResponse as DataQualityAccelSanityPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualityOutliersResponse as DataQualityOutliersPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualityRequiredMissingPctResponse as DataQualityRequiredMissingPctPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualityResponse as DataQualityPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualitySpeedCoverageResponse as DataQualitySpeedCoveragePayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    LocationIntensitySummaryResponse as LocationIntensitySummaryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    OutlierSummaryResponse as OutlierSummaryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseInfoResponse as PhaseInfoPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseIntensityStatsResponse as PhaseIntensityStatsPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseSegmentSummaryResponse as PhaseSegmentSummaryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseTimelineEntryResponse as PhaseTimelineEntryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    SpeedStatsResponse as SpeedStatsPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    StrengthBucketDistributionResponse as StrengthBucketDistributionPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    TestPlanStepResponse as TestPlanStepPayload,
)

__all__ = [
    "AmpVsPhaseRow",
    "AmplitudeMetric",
    "DataQualityAccelSanityPayload",
    "DataQualityOutliersPayload",
    "DataQualityPayload",
    "DataQualityRequiredMissingPctPayload",
    "DataQualitySpeedCoveragePayload",
    "FindingEvidenceMetrics",
    "FreqVsSpeedByFindingSeries",
    "LocationHotspotPayload",
    "LocationIntensitySummaryPayload",
    "MatchedAmpVsSpeedSeries",
    "MatchedPoint",
    "OutlierSummaryPayload",
    "PeakTableRow",
    "PhaseBoundary",
    "PhaseEvidence",
    "PhaseInfoPayload",
    "PhaseIntensityStatsPayload",
    "PhaseSegmentOut",
    "PhaseSegmentSummaryPayload",
    "PhaseSpeedBreakdownRow",
    "PhaseTimelineEntryPayload",
    "PlotDataResult",
    "RunSuitabilityCheck",
    "SpectrogramResult",
    "SpeedBreakdownRow",
    "SpeedStatsPayload",
    "StrengthBucketDistributionPayload",
    "SummaryWarningPayload",
    "TestPlanStepPayload",
]
