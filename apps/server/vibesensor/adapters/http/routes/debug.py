"""Debug endpoints – spectrum and raw samples."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, HTTPException, Query

from vibesensor.shared.types.payloads import (
    DebugSpectrumErrorPayload,
    DebugSpectrumPayload,
    RawSamplesErrorPayload,
    RawSamplesPayload,
)

from ._helpers import normalize_client_id_or_400

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor

__all__ = ["create_debug_routes"]


def create_debug_routes(processor: SignalProcessor) -> APIRouter:
    """Create and return the internal debug API routes."""
    router = APIRouter()

    @router.get("/api/debug/spectrum/{client_id}")
    async def debug_spectrum(
        client_id: str,
    ) -> DebugSpectrumPayload | DebugSpectrumErrorPayload:
        """Detailed spectrum debug info for independent verification."""
        normalized = normalize_client_id_or_400(client_id)
        result = processor.debug_spectrum(normalized)
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(
                status_code=404,
                detail=cast("DebugSpectrumErrorPayload", result)["error"],
            )
        return result

    @router.get("/api/debug/raw-samples/{client_id}")
    async def debug_raw_samples(
        client_id: str,
        n: int = Query(default=2048, ge=1, le=6400),
    ) -> RawSamplesPayload | RawSamplesErrorPayload:
        """Raw time-domain samples in g for offline analysis."""
        normalized = normalize_client_id_or_400(client_id)
        result = processor.raw_samples(normalized, n_samples=n)
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(
                status_code=404,
                detail=cast("RawSamplesErrorPayload", result)["error"],
            )
        return result

    return router
