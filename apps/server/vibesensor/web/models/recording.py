"""Recording-status HTTP API models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from vibesensor.recording.lifecycle_state import RecordingStopReason
from vibesensor.recording.run_schema import GuidedPhaseName


class RecordingCaptureReadinessCheckResponse(BaseModel):
    """One capture-readiness checklist item returned by the recording status route."""

    check_key: str
    state: Literal["pass", "warn", "fail"]
    reason_key: str | None = None
    details: dict[str, int | float | str] = Field(default_factory=dict)


class RecordingCaptureCapabilitiesResponse(BaseModel):
    """Which order families the active car can test; informational, never blocks capture."""

    wheel: Literal["ok", "missing_tire"]
    driveline: Literal["ok", "missing_final_drive", "missing_tire"]
    engine: Literal["measured", "estimated_top_gear", "missing"]


class RecordingCaptureReadinessResponse(BaseModel):
    """Backend-owned live capture-readiness summary for idle/pre-record states."""

    is_ready: bool
    checks: list[RecordingCaptureReadinessCheckResponse]
    capabilities: RecordingCaptureCapabilitiesResponse | None = Field(
        default=None, description="`null` without an active car."
    )


class GuidedPhaseRequest(BaseModel):
    """Request body that marks the guided test-drive step the driver starts now."""

    phase: GuidedPhaseName | None = Field(
        description="`sweep`, `hold`, or `coast_down`; `null` ends the guided test.",
    )


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
    guided_phase: GuidedPhaseName | None = Field(
        default=None,
        description="The guided test-drive step in progress (sweep, hold, coast_down), if any.",
    )
    guided_phases_completed: list[GuidedPhaseName] = Field(
        default_factory=list,
        description=(
            "Guided test-drive steps finished so far in the current recording, in the "
            "order first finished; lets the Live page restore the guided panel after a reload."
        ),
    )
    last_stop_reason: RecordingStopReason | None = Field(
        default=None,
        description=(
            "Why the most recent run stopped; cleared when a new run starts. "
            "`max_duration` means it hit the 30-minute recording limit."
        ),
    )
