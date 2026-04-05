"""Speed-source settings routes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.adapters.http._helpers import OpenAPIResponses
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models import (
    SpeedSourceRequest,
    SpeedSourceResponse,
    SpeedSourceStatusResponse,
)
from vibesensor.adapters.http.settings.dependencies import SpeedSourceRouteDeps
from vibesensor.shared.types.speed_source_config import (
    SpeedSourcePayload as BackendSpeedSourcePayload,
)
from vibesensor.shared.types.speed_source_config import SpeedSourceUpdatePayload

if TYPE_CHECKING:
    from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot

_UPDATE_SPEED_SOURCE_RESPONSES: OpenAPIResponses = {
    400: {"description": "The requested speed-source configuration is invalid."},
}


def _speed_source_response(payload: BackendSpeedSourcePayload) -> SpeedSourceResponse:
    return SpeedSourceResponse(
        speed_source=payload["speedSource"],
        manual_speed_kph=payload["manualSpeedKph"],
        stale_timeout_s=payload["staleTimeoutS"],
        obd_device_mac=payload.get("obdDeviceMac"),
        obd_device_name=payload.get("obdDeviceName"),
    )


def _speed_source_status_response(
    snapshot: SpeedSourceStatusSnapshot,
) -> SpeedSourceStatusResponse:
    return SpeedSourceStatusResponse(
        gps_enabled=snapshot.gps_enabled,
        connection_state=snapshot.connection_state,
        device=snapshot.device,
        fix_mode=snapshot.fix_mode,
        fix_dimension=snapshot.fix_dimension,
        speed_confidence=snapshot.speed_confidence,
        epx_m=snapshot.epx_m,
        epy_m=snapshot.epy_m,
        epv_m=snapshot.epv_m,
        last_update_age_s=snapshot.last_update_age_s,
        raw_speed_kmh=snapshot.raw_speed_kmh,
        effective_speed_kmh=snapshot.effective_speed_kmh,
        last_error=snapshot.last_error,
        reconnect_delay_s=snapshot.reconnect_delay_s,
        fallback_active=snapshot.fallback_active,
        speed_source=snapshot.speed_source,
        stale_timeout_s=snapshot.stale_timeout_s,
    )


def _speed_source_update_payload(req: SpeedSourceRequest) -> SpeedSourceUpdatePayload:
    payload: SpeedSourceUpdatePayload = {}
    if req.speed_source is not None:
        payload["speedSource"] = req.speed_source
    if req.manual_speed_kph is not None:
        payload["manualSpeedKph"] = req.manual_speed_kph
    if req.stale_timeout_s is not None:
        payload["staleTimeoutS"] = req.stale_timeout_s
    if req.obd_device_mac is not None:
        payload["obdDeviceMac"] = req.obd_device_mac
    if req.obd_device_name is not None:
        payload["obdDeviceName"] = req.obd_device_name
    return payload


def create_speed_source_routes(deps: SpeedSourceRouteDeps) -> APIRouter:
    """Create routes for persisted speed-source settings and status."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def get_speed_source() -> SpeedSourceResponse:
        """Return the persisted speed-source configuration used for order tracking."""

        return _speed_source_response(deps.speed_source_service.get_speed_source())

    @router.put(
        "/api/settings/speed-source",
        response_model=SpeedSourceResponse,
        responses=_UPDATE_SPEED_SOURCE_RESPONSES,
    )
    async def update_speed_source(req: SpeedSourceRequest) -> SpeedSourceResponse:
        """Update the preferred speed source, manual fallback speed, and staleness timeout."""

        payload = _speed_source_update_payload(req)
        try:
            result = await asyncio.to_thread(
                deps.speed_source_service.update_speed_source,
                payload,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        return _speed_source_response(result)

    @router.get("/api/settings/speed-source/status", response_model=SpeedSourceStatusResponse)
    async def get_speed_source_status() -> SpeedSourceStatusResponse:
        """Return the live selected-speed-source connection state and effective speed status."""

        return _speed_source_status_response(deps.speed_status_service.status_snapshot())

    return router
