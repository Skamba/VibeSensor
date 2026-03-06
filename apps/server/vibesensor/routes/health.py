"""Health check endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..api_models import HealthResponse

if TYPE_CHECKING:
    from ..runtime import RuntimeState


def create_health_routes(state: RuntimeState) -> APIRouter:
    """Create and return the health-check API routes."""
    router = APIRouter()

    @router.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return {
            "status": "ok",
            "processing_state": state.processing_state,
            "processing_failures": state.processing_failure_count,
            "intake_stats": state.processor.intake_stats(),
        }

    return router
