"""Recording control endpoints – start/stop logging, status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.shared.types.api_models import RecordingStatusResponse

if TYPE_CHECKING:
    from vibesensor.use_cases.run import RunRecorder

__all__ = ["create_recording_routes"]


def create_recording_routes(
    run_recorder: RunRecorder,
) -> APIRouter:
    """Create and return the run-recording / logging API routes."""
    router = APIRouter()

    @router.get("/api/recording/status", response_model=RecordingStatusResponse)
    async def get_logging_status() -> RecordingStatusResponse:
        return RecordingStatusResponse(**run_recorder.status())

    @router.post("/api/recording/start", response_model=RecordingStatusResponse)
    async def start_logging() -> RecordingStatusResponse:
        return RecordingStatusResponse(**run_recorder.start_recording())

    @router.post("/api/recording/stop", response_model=RecordingStatusResponse)
    async def stop_logging() -> RecordingStatusResponse:
        return RecordingStatusResponse(**run_recorder.stop_recording())

    return router
