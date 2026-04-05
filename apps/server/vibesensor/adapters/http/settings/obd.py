"""Bluetooth OBD admin routes under the settings API surface."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

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
    ObdDeviceResponse,
    ObdPairRequest,
    ObdPairResponse,
    ObdScanResponse,
    ObdStatusResponse,
)
from vibesensor.adapters.http.obd_status_presentation import obd_debug_hint
from vibesensor.adapters.http.settings.dependencies import ObdAdminRouteDeps

if TYPE_CHECKING:
    from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot

_OBD_ADMIN_RESPONSES: OpenAPIResponses = {
    503: {"description": "Bluetooth OBD helper unavailable or the requested action failed."},
}


def _obd_device_response(snapshot: ObdDeviceSnapshot) -> ObdDeviceResponse:
    return ObdDeviceResponse(
        mac_address=snapshot.mac_address,
        name=snapshot.name,
        paired=snapshot.paired,
        trusted=snapshot.trusted,
        connected=snapshot.connected,
        rfcomm_channel=snapshot.rfcomm_channel,
    )


def _obd_pair_response(
    *,
    configured_device_mac: str,
    configured_device_name: str | None,
    snapshot: ObdDeviceSnapshot,
) -> ObdPairResponse:
    return ObdPairResponse(
        configured_device_mac=configured_device_mac,
        configured_device_name=configured_device_name,
        paired=snapshot.paired,
        trusted=snapshot.trusted,
        connected=snapshot.connected,
        rfcomm_channel=snapshot.rfcomm_channel,
    )


def _obd_status_response(snapshot: ObdStatusSnapshot) -> ObdStatusResponse:
    return ObdStatusResponse(
        configured_device_mac=snapshot.configured_device_mac,
        configured_device_name=snapshot.configured_device_name,
        connection_state=snapshot.connection_state,
        device_mac=snapshot.device_mac,
        device_name=snapshot.device_name,
        paired=snapshot.paired,
        trusted=snapshot.trusted,
        connected=snapshot.connected,
        rfcomm_channel=snapshot.rfcomm_channel,
        last_sample_age_s=snapshot.last_sample_age_s,
        last_speed_kmh=snapshot.last_speed_kmh,
        last_rpm=snapshot.last_rpm,
        rpm_sample_age_s=snapshot.rpm_sample_age_s,
        rpm_target_interval_ms=snapshot.rpm_target_interval_ms,
        rpm_effective_hz=snapshot.rpm_effective_hz,
        request_rtt_ms=snapshot.request_rtt_ms,
        timeout_count=snapshot.timeout_count,
        error_count=snapshot.error_count,
        poll_mode=snapshot.poll_mode,
        backoff_active=snapshot.backoff_active,
        last_error=snapshot.last_error,
        last_raw_response=snapshot.last_raw_response,
        reconnect_delay_s=snapshot.reconnect_delay_s,
        debug_hint=obd_debug_hint(snapshot),
    )


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
        return ObdScanResponse(devices=[_obd_device_response(device) for device in devices])

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
        return _obd_pair_response(
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
        return _obd_status_response(snapshot)

    return router
