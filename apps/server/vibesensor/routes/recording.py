"""Recording control endpoints – start/stop logging, status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..api_models import RecordingStatusResponse

if TYPE_CHECKING:
    from ..metrics_log import RunRecorder

__all__ = ["create_recording_routes"]


def create_recording_routes(
    metrics_logger: RunRecorder,
) -> APIRouter:
    """Create and return the run-recording / logging API routes."""
    router = APIRouter()

    @router.get("/api/logging/status", response_model=RecordingStatusResponse)
    async def get_logging_status() -> RecordingStatusResponse:
        return RecordingStatusResponse(**metrics_logger.status())

    @router.post("/api/logging/start", response_model=RecordingStatusResponse)
    async def start_logging() -> RecordingStatusResponse:
        return RecordingStatusResponse(**metrics_logger.start_recording())

    @router.post("/api/logging/stop", response_model=RecordingStatusResponse)
    async def stop_logging() -> RecordingStatusResponse:
        return RecordingStatusResponse(**metrics_logger.stop_recording())

    return router
