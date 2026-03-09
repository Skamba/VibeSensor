"""Recording control endpoints – start/stop logging, status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..api_models import LoggingStatusResponse

if TYPE_CHECKING:
    from ..metrics_log import MetricsLogger

__all__ = ["create_recording_routes"]


def create_recording_routes(
    metrics_logger: MetricsLogger,
) -> APIRouter:
    """Create and return the run-recording / logging API routes."""
    router = APIRouter()

    @router.get("/api/logging/status", response_model=LoggingStatusResponse)
    async def get_logging_status() -> LoggingStatusResponse:
        return LoggingStatusResponse(**metrics_logger.status())

    @router.post("/api/logging/start", response_model=LoggingStatusResponse)
    async def start_logging() -> LoggingStatusResponse:
        return LoggingStatusResponse(**metrics_logger.start_logging())

    @router.post("/api/logging/stop", response_model=LoggingStatusResponse)
    async def stop_logging() -> LoggingStatusResponse:
        return LoggingStatusResponse(**metrics_logger.stop_logging())

    return router
