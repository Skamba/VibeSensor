"""History HTTP API models.

The persisted analysis summary and its nested rows are defined once in
``vibesensor.summary.contracts`` (``AnalysisSummary``) and
used directly as the ``HistoryRunResponse.analysis`` schema; this module only
defines endpoint-specific wrappers.
"""

from __future__ import annotations

from typing import Annotated, Literal, Required, TypedDict

from pydantic import BaseModel, ConfigDict, Field, with_config

from vibesensor.summary.contracts import (
    AnalysisSummary,
    AnalysisSummaryCoreResponse,
)
from vibesensor.web.models.base import ApiPayloadObject, _StrictBase


class HistoryArtifactAvailabilityResponse(BaseModel):
    """Response body describing persisted artifact availability for a history run."""

    raw_capture: Literal["not_recorded", "pending", "available", "missing", "degraded"]


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
    start_time_unverified: bool = Field(
        default=False,
        description="The run started before the Pi clock was set (no NTP, no browser "
        "report), so start_time_utc and end_time_utc are wrong; the duration is right.",
    )
    interrupted: bool = Field(
        default=False,
        description="The recording was cut off before Stop (power lost or the server "
        "stopped); startup recovered it from the data saved until then.",
    )
    created_at: str
    raw_sample_count: int | None = Field(
        default=None,
        description="Accelerometer samples in the raw capture across all sensors; "
        "null when the run has no raw capture.",
    )
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
class HistoryOwnerDiagramMarkerResponse(TypedDict):
    """One sensor on the car diagram; ``ratio`` 1.0 is the strongest location."""

    code: str
    label: str
    value: str
    ratio: float | None
    strongest: bool


@with_config(ConfigDict(extra="forbid"))
class HistoryOwnerDiagramResponse(TypedDict):
    """The report's top-view car diagram: the highlighted zone and a level per sensor."""

    zone: str | None
    markers: list[HistoryOwnerDiagramMarkerResponse]
    front_label: str


@with_config(ConfigDict(extra="forbid"))
class HistoryOwnerPageResponse(TypedDict):
    """Page 1 of the PDF report, localized: the owner's verdict and what to do next.

    Built by ``vibesensor.report.view_model.build_owner_page``, the same
    function the PDF draws page 1 from; History renders it as is.
    """

    verdict: Literal["fault", "weak_evidence", "no_fault"]
    result: str
    tone: Literal["good", "strong", "moderate", "muted"]
    headline: str
    level: Literal["strong", "moderate", "weak"] | None
    confidence_label: str
    level_word: str | None
    level_meaning: str | None
    description: str
    candidate: str | None
    reasons_title: str | None
    reasons: list[str]
    covered_title: str | None
    covered: str | None
    not_covered_title: str | None
    not_covered: list[str]
    felt_title: str | None
    felt: str | None
    next_step_title: str
    confirm_title: str | None
    confirm: str | None
    next_step: str
    fallback_step: str | None
    recapture_title: str | None
    recapture: list[str]
    verify_title: str | None
    verify: str | None
    diagram: HistoryOwnerDiagramResponse


@with_config(ConfigDict(extra="forbid"))
class HistoryInsightsResponse(AnalysisSummaryCoreResponse, total=False):
    """Response body for the localized history insights endpoint payload."""

    status: Annotated[Literal["complete"], Field(default="complete")]
    warnings: list[HistoryInsightWarningResponse]
    owner: Required[HistoryOwnerPageResponse]


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str
