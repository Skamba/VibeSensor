"""Health check endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..api_models import HealthResponse

if TYPE_CHECKING:
    from ..processing import SignalProcessor
    from ..runtime.processing_loop import ProcessingLoopState


def create_health_routes(
    loop_state: ProcessingLoopState,
    processor: SignalProcessor,
) -> APIRouter:
    """Create and return the health-check API routes."""
    router = APIRouter()

    @router.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        failures = loop_state.processing_failure_count
        return {
            "status": "ok" if failures == 0 else "degraded",
            "processing_state": loop_state.processing_state,
            "processing_failures": failures,
            "intake_stats": processor.intake_stats(),
        }

    return router
