"""Recording-status HTTP API models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from vibesensor.domain.capture_readiness import (
    DrivelineCapability,
    EngineCapability,
    WheelCapability,
)
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

    wheel: WheelCapability
    driveline: DrivelineCapability
    engine: EngineCapability


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
        description="`sweep`, `hold`, `coast_down`, or `brake`; `null` ends the guided test.",
    )


class RecordingStatusResponse(BaseModel):
    """Response body with the current recording (run-logging) status."""

    enabled: bool
    run_id: str | None
    write_error: str | None
    analysis_in_progress: bool
    start_time_utc: str | None = None
    elapsed_s: float | None = Field(
        default=None,
        description=(
            "Seconds the current run has been recording, on the Pi's monotonic clock; "
            "right even when the Pi wall clock (and so `start_time_utc`) is wrong. "
            "`null` when not recording."
        ),
    )
    samples_written: int = 0
    samples_dropped: int = 0
    raw_samples_written: int = Field(
        default=0,
        description=(
            "Raw accelerometer samples stored so far for the run, all sensors together; "
            "the same count History shows as the run's raw samples. `samples_written` "
            "counts the analysis windows instead."
        ),
    )
    last_completed_run_id: str | None = None
    last_completed_run_error: str | None = None
    capture_readiness: RecordingCaptureReadinessResponse | None = None
    guided_phase: GuidedPhaseName | None = Field(
        default=None,
        description=(
            "The guided test-drive step in progress (sweep, hold, coast_down, brake), if any."
        ),
    )
    guided_phases_completed: list[GuidedPhaseName] = Field(
        default_factory=list,
        description=(
            "Guided test-drive steps finished so far in the current recording, in the "
            "order first finished; lets the Live page restore the guided panel after a reload."
        ),
    )
    guided_brake_stops: int = Field(
        default=0,
        description=(
            "Firm stops counted so far in the current recording's guided brake step, by "
            "the analysis's own braking rule; a stop counts about 4 s after it ends."
        ),
    )
    last_stop_reason: RecordingStopReason | None = Field(
        default=None,
        description=(
            "Why the most recent run stopped; cleared when a new run starts. "
            "`max_duration` means it hit the 30-minute recording limit; "
            "`no_data_timeout` means no sensor data arrived for `no_data_timeout_s`."
        ),
    )
    no_data_s: float | None = Field(
        default=None,
        description=(
            "Seconds since sensor data last arrived for the current run; `null` when "
            "not recording. The run stops by itself once this reaches `no_data_timeout_s`."
        ),
    )
    no_data_timeout_s: float = Field(
        default=0.0,
        description="Sensor silence, in seconds, after which a run stops by itself.",
    )
    last_run_id: str | None = Field(
        default=None,
        description=(
            "The run most recently stopped since the server started; cleared when a new "
            "run starts. Until then `samples_written`, `samples_dropped` and "
            "`raw_samples_written` describe it."
        ),
    )
