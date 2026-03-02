"""Recording control endpoints – start/stop logging, status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..api_models import LoggingStatusResponse

if TYPE_CHECKING:
    from ..app import RuntimeState


def create_recording_routes(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/logging/status", response_model=LoggingStatusResponse)
    async def get_logging_status() -> LoggingStatusResponse:
        return state.metrics_logger.status()

    @router.post("/api/logging/start", response_model=LoggingStatusResponse)
    async def start_logging() -> LoggingStatusResponse:
        state.live_diagnostics.reset()
        return state.metrics_logger.start_logging()

    @router.post("/api/logging/stop", response_model=LoggingStatusResponse)
    async def stop_logging() -> LoggingStatusResponse:
        return state.metrics_logger.stop_logging()

    return router
