"""Recording control endpoints – start/stop logging, status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..api_models import LoggingStatusResponse

if TYPE_CHECKING:
    from ..runtime import RuntimeState

__all__ = ["create_recording_routes"]


def create_recording_routes(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    # Local-bind frequently accessed sub-objects so endpoint closures avoid
    # repeated attribute lookups on *state* for every request.
    _logger = state.metrics_logger
    _diagnostics = state.live_diagnostics

    @router.get("/api/logging/status", response_model=LoggingStatusResponse)
    async def get_logging_status() -> LoggingStatusResponse:
        return _logger.status()

    @router.post("/api/logging/start", response_model=LoggingStatusResponse)
    async def start_logging() -> LoggingStatusResponse:
        _diagnostics.reset()
        return _logger.start_logging()

    @router.post("/api/logging/stop", response_model=LoggingStatusResponse)
    async def stop_logging() -> LoggingStatusResponse:
        return _logger.stop_logging()

    return router
