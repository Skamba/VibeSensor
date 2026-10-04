"""Recording control endpoints – start/stop logging, status."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.web.models.recording import (
    GuidedPhaseRequest,
    RecordingCaptureCapabilitiesResponse,
    RecordingCaptureReadinessCheckResponse,
    RecordingCaptureReadinessResponse,
    RecordingStatusResponse,
)

if TYPE_CHECKING:
    from vibesensor.recording.recorder import RunRecorder
    from vibesensor.recording.status_reporting import RunRecorderStatusSnapshot

__all__ = ["create_recording_routes"]


def _capture_readiness_response(
    snapshot: RunRecorderStatusSnapshot,
) -> RecordingCaptureReadinessResponse | None:
    readiness = snapshot.capture_readiness
    if readiness is None:
        return None
    return RecordingCaptureReadinessResponse(
        is_ready=readiness.is_ready,
        checks=[
            RecordingCaptureReadinessCheckResponse(
                check_key=check.check_key,
                state=check.state,
                reason_key=check.reason_key,
                details=check.details_dict,
            )
            for check in readiness.checks
        ],
        capabilities=(
            RecordingCaptureCapabilitiesResponse(
                wheel=capabilities.wheel,
                driveline=capabilities.driveline,
                engine=capabilities.engine,
            )
            if (capabilities := readiness.capabilities) is not None
            else None
        ),
    )


def _recording_status_response(snapshot: RunRecorderStatusSnapshot) -> RecordingStatusResponse:
    return RecordingStatusResponse(
        enabled=snapshot.enabled,
        run_id=snapshot.run_id,
        write_error=snapshot.write_error,
        analysis_in_progress=snapshot.analysis_in_progress,
        start_time_utc=snapshot.start_time_utc,
        samples_written=snapshot.samples_written,
        samples_dropped=snapshot.samples_dropped,
        last_completed_run_id=snapshot.last_completed_run_id,
        last_completed_run_error=snapshot.last_completed_run_error,
        capture_readiness=_capture_readiness_response(snapshot),
        last_stop_reason=snapshot.last_stop_reason,
        last_run_id=snapshot.last_run_id,
        guided_phase=snapshot.guided_phase,
        guided_phases_completed=list(snapshot.guided_phases_completed),
    )


def create_recording_routes(
    run_recorder: RunRecorder,
) -> APIRouter:
    """Create and return the run-recording / logging API routes."""
    router = APIRouter(tags=["recording"])

    @router.get("/api/recording/status", response_model=RecordingStatusResponse)
    async def get_logging_status() -> RecordingStatusResponse:
        """Return the current recording state, counters, and last completed run details."""
        return _recording_status_response(await asyncio.to_thread(run_recorder.status))

    @router.post("/api/recording/start", response_model=RecordingStatusResponse)
    async def start_logging() -> RecordingStatusResponse:
        """Start recording a new run and return the updated recorder status snapshot."""
        return _recording_status_response(await asyncio.to_thread(run_recorder.start_recording))

    @router.post("/api/recording/stop", response_model=RecordingStatusResponse)
    async def stop_logging() -> RecordingStatusResponse:
        """Stop the active recording and return the updated recorder status snapshot."""
        return _recording_status_response(await asyncio.to_thread(run_recorder.stop_recording))

    @router.post("/api/recording/guided-phase", response_model=RecordingStatusResponse)
    async def mark_guided_phase(body: GuidedPhaseRequest) -> RecordingStatusResponse:
        """Mark the guided test-drive step (sweep, hold, neutral coast-down) starting now."""
        return _recording_status_response(
            await asyncio.to_thread(run_recorder.mark_guided_phase, body.phase)
        )

    return router
