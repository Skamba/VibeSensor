"""History HTTP API models.

The persisted analysis summary and its nested rows are defined once in
``vibesensor.shared.types.history_analysis_contracts`` (``AnalysisSummary``) and
used directly as the ``HistoryRunResponse.analysis`` schema; this module only
defines endpoint-specific wrappers.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, with_config

from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummary,
    AnalysisSummaryCoreResponse,
)

from .base import ApiPayloadObject, _StrictBase


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


class HistoryRunResponse(_StrictBase):
    """Response body for a single history run with metadata and optional analysis."""

    run_id: str
    status: str
    sample_count: int
    error_message: str | None = None
    metadata: ApiPayloadObject = Field(default_factory=dict)
    analysis: AnalysisSummary | None = None
    lifecycle: HistoryRunLifecycleResponse | None = None
    artifact_availability: HistoryArtifactAvailabilityResponse | None = None
    raw_capture_finalize: HistoryRawCaptureFinalizeResponse | None = None
    finalization_stages: list[HistoryFinalizationStageResponse] | None = None
    raw_capture_quality: HistoryRawCaptureQualityResponse | None = None
    fallback_reasons: list[str] | None = None


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


@with_config(ConfigDict(extra="forbid"))
class HistoryInsightsResponse(AnalysisSummaryCoreResponse, total=False):
    """Response body for the localized history insights endpoint payload."""

    status: Annotated[Literal["complete"], Field(default="complete")]
    warnings: list[HistoryInsightWarningResponse]


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str
