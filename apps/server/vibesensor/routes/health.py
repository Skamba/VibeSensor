"""Health check endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..api_models import HealthResponse
from ..runtime.health_snapshot import build_health_snapshot

if TYPE_CHECKING:
    from ..metrics_log import RunRecorder
    from ..processing import SignalProcessor
    from ..registry import ClientRegistry
    from ..runtime.health_state import RuntimeHealthState
    from ..runtime.processing_loop import ProcessingLoopState


def create_health_routes(
    loop_state: ProcessingLoopState,
    health_state: RuntimeHealthState,
    processor: SignalProcessor,
    registry: ClientRegistry,
    metrics_logger: RunRecorder,
) -> APIRouter:
    """Create and return the health-check API routes."""
    router = APIRouter()

    @router.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            **build_health_snapshot(loop_state, health_state, processor, registry, metrics_logger)
        )

    return router
