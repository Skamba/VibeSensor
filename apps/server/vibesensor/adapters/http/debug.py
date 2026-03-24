"""Debug endpoints – spectrum and raw samples."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeGuard

from fastapi import APIRouter, HTTPException, Query

from vibesensor.adapters.http._helpers import OpenAPIResponses, normalize_client_id_or_400
from vibesensor.shared.types.payload_types import (
    DebugSpectrumErrorPayload,
    DebugSpectrumPayload,
    RawSamplesErrorPayload,
    RawSamplesPayload,
)

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor

__all__ = ["create_debug_routes"]

_DEBUG_SENSOR_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid sensor identifier."},
    404: {"description": "No debug data is available for the requested sensor."},
}


def _is_debug_spectrum_error_payload(
    payload: DebugSpectrumPayload | DebugSpectrumErrorPayload,
) -> TypeGuard[DebugSpectrumErrorPayload]:
    return "error" in payload


def _is_debug_spectrum_payload(
    payload: DebugSpectrumPayload | DebugSpectrumErrorPayload,
) -> TypeGuard[DebugSpectrumPayload]:
    return "error" not in payload


def _is_raw_samples_error_payload(
    payload: RawSamplesPayload | RawSamplesErrorPayload,
) -> TypeGuard[RawSamplesErrorPayload]:
    return "error" in payload


def _is_raw_samples_payload(
    payload: RawSamplesPayload | RawSamplesErrorPayload,
) -> TypeGuard[RawSamplesPayload]:
    return "error" not in payload


def create_debug_routes(processor: SignalProcessor) -> APIRouter:
    """Create and return the internal debug API routes."""
    router = APIRouter(tags=["debug"])

    @router.get(
        "/api/debug/spectrum/{client_id}",
        response_model=DebugSpectrumPayload,
        responses=_DEBUG_SENSOR_RESPONSES,
    )
    async def debug_spectrum(client_id: str) -> DebugSpectrumPayload:
        """Detailed spectrum debug info for independent verification."""
        normalized = normalize_client_id_or_400(client_id)
        result = processor.debug_spectrum(normalized)
        if _is_debug_spectrum_error_payload(result):
            raise HTTPException(
                status_code=404,
                detail=result["error"],
            )
        if _is_debug_spectrum_payload(result):
            return result
        raise AssertionError("Unreachable debug spectrum payload state")

    @router.get(
        "/api/debug/raw-samples/{client_id}",
        response_model=RawSamplesPayload,
        responses=_DEBUG_SENSOR_RESPONSES,
    )
    async def debug_raw_samples(
        client_id: str,
        n: int = Query(
            default=2048,
            ge=1,
            le=6400,
            description="Number of recent raw samples to return.",
        ),
    ) -> RawSamplesPayload:
        """Raw time-domain samples in g for offline analysis."""
        normalized = normalize_client_id_or_400(client_id)
        result = processor.raw_samples(normalized, n_samples=n)
        if _is_raw_samples_error_payload(result):
            raise HTTPException(
                status_code=404,
                detail=result["error"],
            )
        if _is_raw_samples_payload(result):
            return result
        raise AssertionError("Unreachable raw-samples payload state")

    return router
