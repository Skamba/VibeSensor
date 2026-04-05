"""Speed-source settings routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from vibesensor.adapters.http._helpers import OpenAPIResponses
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models import (
    SpeedSourceRequest,
    SpeedSourceResponse,
    SpeedSourceStatusResponse,
)
from vibesensor.adapters.http.settings.dependencies import SpeedSourceRouteDeps
from vibesensor.adapters.http.settings.presentation import speed_source_status_response
from vibesensor.shared.boundaries.settings import (
    speed_source_response_payload,
    speed_source_update_payload_from_mapping,
)

_UPDATE_SPEED_SOURCE_RESPONSES: OpenAPIResponses = {
    400: {"description": "The requested speed-source configuration is invalid."},
}


def create_speed_source_routes(deps: SpeedSourceRouteDeps) -> APIRouter:
    """Create routes for persisted speed-source settings and status."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def get_speed_source() -> SpeedSourceResponse:
        """Return the persisted speed-source configuration used for order tracking."""

        return SpeedSourceResponse.model_validate(
            speed_source_response_payload(deps.speed_source_service.get_speed_source())
        )

    @router.put(
        "/api/settings/speed-source",
        response_model=SpeedSourceResponse,
        responses=_UPDATE_SPEED_SOURCE_RESPONSES,
    )
    async def update_speed_source(req: SpeedSourceRequest) -> SpeedSourceResponse:
        """Update the preferred speed source, manual fallback speed, and staleness timeout."""

        payload = speed_source_update_payload_from_mapping(req.model_dump(exclude_none=True))
        try:
            result = await asyncio.to_thread(
                deps.speed_source_service.update_speed_source,
                payload,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        return SpeedSourceResponse.model_validate(speed_source_response_payload(result))

    @router.get("/api/settings/speed-source/status", response_model=SpeedSourceStatusResponse)
    async def get_speed_source_status() -> SpeedSourceStatusResponse:
        """Return the live selected-speed-source connection state and effective speed status."""

        return speed_source_status_response(deps.speed_status_service.status_snapshot())

    return router
