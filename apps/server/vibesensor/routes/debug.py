"""Debug endpoints – spectrum and raw samples."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query

from ._helpers import normalize_client_id_or_400

if TYPE_CHECKING:
    from ..app import RuntimeState


def create_debug_routes(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/debug/spectrum/{client_id}")
    async def debug_spectrum(client_id: str) -> dict[str, Any]:
        """Detailed spectrum debug info for independent verification."""
        normalized = normalize_client_id_or_400(client_id)
        return state.processor.debug_spectrum(normalized)

    @router.get("/api/debug/raw-samples/{client_id}")
    async def debug_raw_samples(
        client_id: str,
        n: int = Query(default=2048, ge=1, le=6400),
    ) -> dict[str, Any]:
        """Raw time-domain samples in g for offline analysis."""
        normalized = normalize_client_id_or_400(client_id)
        return state.processor.raw_samples(normalized, n_samples=n)

    return router
