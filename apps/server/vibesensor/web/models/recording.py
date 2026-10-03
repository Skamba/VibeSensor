"""Recording-status HTTP API models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from vibesensor.recording.lifecycle_state import RecordingStopReason


class RecordingCaptureReadinessCheckResponse(BaseModel):
    """One capture-readiness checklist item returned by the recording status route."""

    check_key: str
    state: Literal["pass", "warn", "fail"]
    reason_key: str | None = None
    details: dict[str, int | float | str] = Field(default_factory=dict)


class RecordingCaptureReadinessResponse(BaseModel):
    """Backend-owned live capture-readiness summary for idle/pre-record states."""

    is_ready: bool
    checks: list[RecordingCaptureReadinessCheckResponse]


class RecordingStatusResponse(BaseModel):
    """Response body with the current recording (run-logging) status."""

    enabled: bool
    run_id: str | None
    write_error: str | None
    analysis_in_progress: bool
    start_time_utc: str | None = None
    samples_written: int = 0
    samples_dropped: int = 0
    last_completed_run_id: str | None = None
    last_completed_run_error: str | None = None
    capture_readiness: RecordingCaptureReadinessResponse | None = None
    last_stop_reason: RecordingStopReason | None = Field(
        default=None,
        description=(
            "Why the most recent run stopped; cleared when a new run starts. "
            "`max_duration` means it hit the 30-minute recording limit."
        ),
    )
