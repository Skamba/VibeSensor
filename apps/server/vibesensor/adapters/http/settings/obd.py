"""Bluetooth OBD admin routes under the settings API surface."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from vibesensor.adapters.http._helpers import (
    OpenAPIResponses,
    normalize_mac_or_400,
)
from vibesensor.adapters.http.error_boundary import (
    http_exception_for_value_error,
    route_errors_to_http,
)
from vibesensor.adapters.http.models import (
    ObdPairRequest,
    ObdPairResponse,
    ObdScanResponse,
    ObdStatusResponse,
)
from vibesensor.adapters.http.settings.dependencies import ObdAdminRouteDeps
from vibesensor.adapters.http.settings.presentation import (
    obd_pair_response,
    obd_scan_response,
    obd_status_response,
)

_OBD_ADMIN_RESPONSES: OpenAPIResponses = {
    503: {"description": "Bluetooth OBD helper unavailable or the requested action failed."},
}


def create_obd_admin_routes(deps: ObdAdminRouteDeps) -> APIRouter:
    """Create routes for Bluetooth OBD scanning, pairing, and status."""

    router = APIRouter(tags=["settings"])

    @router.post(
        "/api/settings/obd/scan",
        response_model=ObdScanResponse,
        responses=_OBD_ADMIN_RESPONSES,
    )
    async def scan_obd_devices() -> ObdScanResponse:
        """Scan nearby Bluetooth OBD adapters using the privileged helper."""

        with route_errors_to_http():
            devices = await asyncio.to_thread(deps.obd_admin_service.scan_obd_devices)
        return obd_scan_response(devices)

    @router.post(
        "/api/settings/obd/pair",
        response_model=ObdPairResponse,
        responses={400: {"description": "Invalid Bluetooth MAC address."}, **_OBD_ADMIN_RESPONSES},
    )
    async def pair_obd_device(req: ObdPairRequest) -> ObdPairResponse:
        """Pair, trust, connect, and persist the selected Bluetooth OBD adapter."""

        normalized_mac = normalize_mac_or_400(req.mac_address)
        with route_errors_to_http():
            device = await asyncio.to_thread(
                deps.obd_admin_service.pair_obd_device,
                normalized_mac,
            )
        try:
            persisted = await asyncio.to_thread(
                deps.speed_source_service.update_speed_source,
                {
                    "obdDeviceMac": device.mac_address,
                    "obdDeviceName": device.name,
                },
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        return obd_pair_response(
            configured_device_mac=str(persisted.get("obdDeviceMac") or device.mac_address),
            configured_device_name=(
                str(persisted.get("obdDeviceName"))
                if persisted.get("obdDeviceName") not in (None, "")
                else device.name
            ),
            snapshot=device,
        )

    @router.get("/api/settings/obd/status", response_model=ObdStatusResponse)
    async def get_obd_status() -> ObdStatusResponse:
        """Return detailed Bluetooth OBD runtime/admin status for diagnostics."""

        with route_errors_to_http():
            await asyncio.to_thread(deps.obd_admin_service.refresh_obd_status)
            snapshot = await asyncio.to_thread(deps.speed_status_service.obd_status)
        return obd_status_response(snapshot)

    return router
