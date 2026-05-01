"""History and finding-oriented HTTP API models.

Stable exact analysis/history view shapes live in
``vibesensor.shared.types.analysis_views``. Canonical shared summary wrappers
live in ``vibesensor.shared.types.history_analysis_contracts`` and are imported
privately here so this module only exports adapter-local wrappers and
localized response models.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Required, TypedDict, cast

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
from vibesensor.shared.types.data_quality_contracts import (
    DataQualityAccelSanityResponse,
    DataQualityOutliersResponse,
    DataQualityRequiredMissingPctResponse,
    DataQualityResponse,
    DataQualitySpeedCoverageResponse,
    OutlierSummaryResponse,
)
from vibesensor.shared.types.history_analysis_contracts import (
    AmplitudeMetric,
    FindingPayload,
    LocationIntensitySummaryResponse,
    OrderTraceSummaryResponse,
    PayloadObject,
    PhaseInfoResponse,
    PhaseIntensityStatsResponse,
    PhaseSegmentSummaryResponse,
    PhaseTimelineEntryResponse,
    RunSuitabilityCheck,
    SpatialEvidenceSummaryResponse,
    SpeedStatsResponse,
    StrengthBucketDistributionResponse,
    SummaryWarningResponse,
    SuspectedVibrationOriginPayload,
    TestPlanStepResponse,
    WholeRunContextIntervalResponse,
    WholeRunDiagnosisSummaryResponse,
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


class HistoryArtifactAvailabilityResponse(BaseModel):
    """Response body describing persisted artifact availability for a history run."""

    raw_capture: Literal["not_recorded", "pending", "available", "missing", "degraded"]
    whole_run_artifacts: Literal["not_recorded", "pending", "available", "missing", "degraded"]


class HistoryRunLifecycleResponse(BaseModel):
    """Response body describing the canonical derived lifecycle for a history run."""

    stage: Literal[
        "recording",
        "post_analysis_pending",
        "post_analysis_running",
        "post_analysis_ready",
        "post_analysis_degraded",
    ]
    raw_capture: Literal["not_recorded", "pending", "ready", "degraded", "missing"]
    whole_run_artifacts: Literal["not_recorded", "pending", "ready", "degraded", "missing"]
    post_analysis: Literal["pending", "running", "ready", "degraded"]
    report: Literal["pending", "ready", "degraded"]


class HistoryRawCaptureFinalizeResponse(BaseModel):
    """Response body describing the persisted raw-capture finalization outcome."""

    status: Literal["completed", "not_configured", "enqueue_timeout", "timeout", "failed"]
    queue_depth: int | None = None
    error_summary: str | None = None


class HistoryFinalizationStageResponse(BaseModel):
    """Response body describing one persisted run-finalization stage outcome."""

    stage_name: str
    status: Literal["ok", "skipped", "degraded", "failed"]
    duration_ms: int
    artifacts_created: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    diagnostic_context: ApiPayloadObject = Field(default_factory=dict)


class HistoryRawCaptureQualityResponse(BaseModel):
    """Response body describing raw-capture loss policy for one run."""

    severity: Literal["ok", "warn", "degraded", "fatal"]
    reason: str
    gate_whole_run: bool
    affected_sensor_count: int = 0
    queue_overflow_sensor_count: int = 0
    total_chunk_count: int = 0
    total_loss_event_count: int = 0
    total_dropped_chunk_count: int = 0
    queue_overflow_chunk_count: int = 0
    max_sensor_drop_ratio: float = 0.0
    max_sensor_loss_events_per_minute: float = 0.0


class HistoryListEntryResponse(BaseModel):
    """Response body for a single history-run list row."""

    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None = None
    created_at: str
    sample_count: int
    car_name: str | None = None
    error_message: str | None = None
    lifecycle: HistoryRunLifecycleResponse | None = None
    artifact_availability: HistoryArtifactAvailabilityResponse | None = None
    raw_capture_finalize: HistoryRawCaptureFinalizeResponse | None = None
    finalization_stages: list[HistoryFinalizationStageResponse] | None = None


class HistoryListResponse(BaseModel):
    """Response body listing recorded run summaries."""

    runs: list[HistoryListEntryResponse]


# Keep plain assignment so ``HistoryRunResponse.analysis`` can name a local HTTP
# alias while preserving the shared ``AnalysisSummaryResponse`` runtime/schema
# identity for OpenAPI generation.
_HistoryRunAnalysisResponse = _SharedAnalysisSummaryResponse


class HistoryRunResponse(_StrictBase):
    """Response body for a single history run with metadata and optional analysis."""

    run_id: str
    status: str
    sample_count: int
    error_message: str | None = None
    metadata: ApiPayloadObject = Field(default_factory=dict)
    analysis: _HistoryRunAnalysisResponse | None = None
    lifecycle: HistoryRunLifecycleResponse | None = None
    artifact_availability: HistoryArtifactAvailabilityResponse | None = None
    raw_capture_finalize: HistoryRawCaptureFinalizeResponse | None = None
    finalization_stages: list[HistoryFinalizationStageResponse] | None = None
    raw_capture_quality: HistoryRawCaptureQualityResponse | None = None


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


class _HistoryInsightsCoreResponse(TypedDict, total=False):
    """HTTP-owned core field wrapper for the localized history insights payload."""

    file_name: Required[str]
    run_id: Required[str]
    case_id: str | None
    rows: Required[int]
    duration_s: Required[float]
    record_length: Required[str]
    lang: Required[str]
    report_date: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sensor_model: str | None
    firmware_version: str | None
    raw_sample_rate_hz: Required[float | None]
    feature_interval_s: Required[float | None]
    fft_window_size_samples: int | None
    fft_window_type: str | None
    peak_picker_method: str | None
    accel_scale_g_per_lsb: Required[float | None]
    incomplete_for_order_analysis: Required[bool]
    metadata: Required[PayloadObject]
    speed_breakdown: Required[list[SpeedBreakdownRow]]
    phase_speed_breakdown: Required[list[PhaseSpeedBreakdownRow]]
    phase_segments: Required[list[PhaseSegmentSummaryResponse]]
    run_noise_baseline_db: Required[float | None]
    speed_breakdown_skipped_reason: Required[PayloadObject | None]
    findings: Required[list[FindingPayload]]
    top_causes: Required[list[FindingPayload]]
    most_likely_origin: Required[SuspectedVibrationOriginPayload]
    test_plan: Required[list[TestPlanStepResponse]]
    phase_timeline: Required[list[PhaseTimelineEntryResponse]]
    whole_run_context_intervals: list[WholeRunContextIntervalResponse]
    whole_run_order_summaries: list[OrderTraceSummaryResponse]
    whole_run_spatial_summaries: list[SpatialEvidenceSummaryResponse]
    whole_run_diagnosis_summaries: list[WholeRunDiagnosisSummaryResponse]
    speed_stats: Required[SpeedStatsResponse]
    speed_stats_by_phase: Required[dict[str, SpeedStatsResponse]]
    phase_info: Required[PhaseInfoResponse]
    sensor_locations: Required[list[str]]
    sensor_locations_connected_throughout: Required[list[str]]
    sensor_count_used: Required[int]
    sensor_intensity_by_location: Required[list[LocationIntensitySummaryResponse]]
    run_suitability: Required[list[RunSuitabilityCheck]]
    data_quality: Required[DataQualityResponse]
    samples: list[PayloadObject]
    plots: PlotDataResult | None
    analysis_metadata: PayloadObject


class HistoryInsightsResponse(_HistoryInsightsCoreResponse, total=False):
    """Response body for the localized history insights endpoint payload."""

    status: Annotated[Literal["complete"], Field(default="complete")]
    warnings: list[HistoryInsightWarningResponse]


cast(Any, HistoryInsightsResponse).__pydantic_config__ = ConfigDict(extra="forbid")


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str
