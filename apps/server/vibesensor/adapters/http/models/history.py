"""History and finding-oriented HTTP API models.

Stable exact analysis/history view shapes live in
``vibesensor.shared.types.analysis_views``. Canonical shared summary wrappers
live in ``vibesensor.shared.types.history_analysis_contracts`` and are imported
privately here so this module only exports adapter-local wrappers and
localized response models.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    DataQualityAccelSanityResponse,
    DataQualityOutliersResponse,
    DataQualityRequiredMissingPctResponse,
    DataQualityResponse,
    DataQualitySpeedCoverageResponse,
    FindingPayload,
    LocationIntensitySummaryResponse,
    OutlierSummaryResponse,
    PhaseInfoResponse,
    PhaseIntensityStatsResponse,
    PhaseSegmentSummaryResponse,
    PhaseTimelineEntryResponse,
    RunSuitabilityCheck,
    SpeedStatsResponse,
    StrengthBucketDistributionResponse,
    SummaryWarningResponse,
    SuspectedVibrationOriginPayload,
    TestPlanStepResponse,
)
from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummaryCoreResponse as _SharedAnalysisSummaryCoreResponse,
)
from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummaryResponse as _SharedAnalysisSummaryResponse,
)

from .base import ApiPayloadObject, _StrictBase

__all__ = [
    "AmplitudeMetric",
    "AmpVsPhaseRow",
    "DataQualityAccelSanityResponse",
    "DataQualityOutliersResponse",
    "DataQualityRequiredMissingPctResponse",
    "DataQualityResponse",
    "DataQualitySpeedCoverageResponse",
    "FindingEvidenceMetrics",
    "FindingPayload",
    "FreqVsSpeedByFindingSeries",
    "LocationHotspotPayload",
    "LocationIntensitySummaryResponse",
    "MatchedAmpVsSpeedSeries",
    "MatchedPoint",
    "OutlierSummaryResponse",
    "PeakTableRow",
    "PhaseBoundary",
    "PhaseEvidence",
    "PhaseInfoResponse",
    "PhaseIntensityStatsResponse",
    "PhaseSegmentOut",
    "PhaseSegmentSummaryResponse",
    "PhaseSpeedBreakdownRow",
    "PhaseTimelineEntryResponse",
    "PlotDataResult",
    "RunSuitabilityCheck",
    "SpectrogramResult",
    "SpeedBreakdownRow",
    "SpeedStatsResponse",
    "StrengthBucketDistributionResponse",
    "SummaryWarningResponse",
    "SuspectedVibrationOriginPayload",
    "TestPlanStepResponse",
]


class HistoryListEntryResponse(BaseModel):
    """Response body for a single history-run list row."""

    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None = None
    created_at: str
    sample_count: int
    error_message: str | None = None


class HistoryListResponse(BaseModel):
    """Response body listing recorded run summaries."""

    runs: list[HistoryListEntryResponse]


class HistoryRunResponse(_StrictBase):
    """Response body for a single history run with metadata and optional analysis."""

    run_id: str
    status: str
    sample_count: int
    error_message: str | None = None
    metadata: ApiPayloadObject = Field(default_factory=dict)
    analysis: _SharedAnalysisSummaryResponse | None = None


class HistoryInsightWarningResponse(BaseModel):
    """Response body for a localized history/run trust warning."""

    code: str
    severity: Literal["warn", "error"]
    applies_to: str
    title: str
    detail: str | None = None


class HistoryInsightsAnalyzingResponse(BaseModel):
    """Response body for a history run whose analysis is still in progress."""

    run_id: str
    status: Literal["analyzing"]


class HistoryInsightsResponse(_SharedAnalysisSummaryCoreResponse, total=False):
    """Response body for the localized history insights endpoint payload."""

    status: Annotated[Literal["complete"], Field(default="complete")]
    warnings: list[HistoryInsightWarningResponse]


def _configure_pydantic_schema(typed_dict: Any) -> None:
    typed_dict.__pydantic_config__ = ConfigDict(extra="forbid")


_configure_pydantic_schema(HistoryInsightsResponse)


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str
