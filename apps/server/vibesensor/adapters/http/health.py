"""Health check endpoint."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.adapters.http.models import HealthResponse
from vibesensor.infra.runtime.health_snapshot import build_system_health_snapshot

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.health_state import RuntimeHealthState
    from vibesensor.infra.runtime.processing_state import ProcessingLoopState
    from vibesensor.infra.runtime.registry import ClientRegistry
    from vibesensor.use_cases.run import RunRecorder


def create_health_routes(
    loop_state: ProcessingLoopState,
    health_state: RuntimeHealthState,
    processor: SignalProcessor,
    registry: ClientRegistry,
    run_recorder: RunRecorder,
) -> APIRouter:
    """Create and return the health-check API routes."""
    router = APIRouter(tags=["health"])

    @router.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Return the current runtime health snapshot for the server and sensor pipeline."""
        return HealthResponse.model_validate(
            await asyncio.to_thread(
                build_system_health_snapshot,
                loop_state,
                health_state,
                processor,
                registry,
                run_recorder,
            )
        )

    return router
