"""Speed-source settings routes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from fastapi import APIRouter

from vibesensor.adapters.http._helpers import OpenAPIResponses
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models.settings import (
    SpeedSourceRequest,
    SpeedSourceResponse,
    SpeedSourceStatusResponse,
)
from vibesensor.adapters.http.settings.dependencies import SpeedSourceRouteDeps
from vibesensor.adapters.http.settings.presentation import speed_source_status_response
from vibesensor.domain.speed_source import SpeedSourceKind
from vibesensor.speed.speed_source_config import SpeedSourcePayload, SpeedSourceUpdatePayload

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


def speed_source_update_payload_from_mapping(
    payload: Mapping[str, object],
) -> SpeedSourceUpdatePayload:
    """Project a request-like mapping into the canonical speed-source update payload."""

    update: SpeedSourceUpdatePayload = {}
    speed_source = payload.get("speed_source")
    if isinstance(speed_source, SpeedSourceKind):
        update["speedSource"] = speed_source
    elif isinstance(speed_source, str):
        update["speedSource"] = SpeedSourceKind(speed_source)
    manual_speed_kph = payload.get("manual_speed_kph")
    if isinstance(manual_speed_kph, (int, float)) and not isinstance(manual_speed_kph, bool):
        update["manualSpeedKph"] = float(manual_speed_kph)
    stale_timeout_s = payload.get("stale_timeout_s")
    if isinstance(stale_timeout_s, (int, float)) and not isinstance(stale_timeout_s, bool):
        update["staleTimeoutS"] = float(stale_timeout_s)
    obd_device_mac = payload.get("obd_device_mac")
    if isinstance(obd_device_mac, str):
        update["obdDeviceMac"] = obd_device_mac
    obd_device_name = payload.get("obd_device_name")
    if isinstance(obd_device_name, str):
        update["obdDeviceName"] = obd_device_name
    return update


def speed_source_response_payload(payload: SpeedSourcePayload) -> dict[str, object]:
    """Project the canonical speed-source payload into the HTTP response shape."""

    return {
        "speed_source": payload["speedSource"],
        "manual_speed_kph": payload["manualSpeedKph"],
        "stale_timeout_s": payload["staleTimeoutS"],
        "obd_device_mac": payload.get("obdDeviceMac"),
        "obd_device_name": payload.get("obdDeviceName"),
    }


__all__ = ["speed_source_response_payload", "speed_source_update_payload_from_mapping"]
