"""Health check endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.adapters.http.models import HealthResponse
from vibesensor.infra.runtime.health_snapshot import build_health_snapshot

if TYPE_CHECKING:
    from vibesensor.infra.metrics import RunRecorder
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.health_state import RuntimeHealthState
    from vibesensor.infra.runtime.processing_loop import ProcessingLoopState
    from vibesensor.infra.runtime.registry import ClientRegistry


def create_health_routes(
    loop_state: ProcessingLoopState,
    health_state: RuntimeHealthState,
    processor: SignalProcessor,
    registry: ClientRegistry,
    run_recorder: RunRecorder,
) -> APIRouter:
    """Create and return the health-check API routes."""
    router = APIRouter()

    @router.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            **build_health_snapshot(loop_state, health_state, processor, registry, run_recorder)
        )

    return router
