"""Bluetooth OBD admin routes under the settings API surface."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from vibesensor.web._helpers import (
    OpenAPIResponses,
    normalize_mac_or_400,
)
from vibesensor.web.error_boundary import (
    http_exception_for_value_error,
    route_errors_to_http,
)
from vibesensor.web.models.settings import (
    ObdPairRequest,
    ObdPairResponse,
    ObdScanResponse,
    ObdStatusResponse,
)
from vibesensor.web.settings.presentation import (
    obd_pair_response,
    obd_scan_response,
    obd_status_response,
)

if TYPE_CHECKING:
    from vibesensor.ingest.registry import ClientRegistry, ExpectedFrameLoss
    from vibesensor.recording.recorder import RunRecorder
    from vibesensor.settings.speed_source_runtime import SpeedSourceSettingsService
    from vibesensor.speed.obd.service import ObdService
    from vibesensor.speed.source_coordinator import SpeedSourceObservationService


_OBD_ADMIN_RESPONSES: OpenAPIResponses = {
    409: {"description": "A recording is running; Bluetooth would interrupt its sensor data."},
    503: {"description": "Bluetooth OBD helper unavailable or the requested action failed."},
}
_RECORDING_ACTIVE_DETAIL = {
    "bluetooth_scan": (
        "Stop the recording before scanning: a Bluetooth scan interrupts sensor data "
        "for about 10 seconds."
    ),
    "bluetooth_pairing": (
        "Stop the recording before pairing: Bluetooth pairing interrupts sensor data."
    ),
}


def create_obd_admin_routes(
    speed_source_service: SpeedSourceSettingsService,
    speed_status_service: SpeedSourceObservationService,
    obd_admin_service: ObdService,
    registry: ClientRegistry,
    run_recorder: RunRecorder,
) -> APIRouter:
    """Create routes for Bluetooth OBD scanning, pairing, and status.

    The Pi's Wi-Fi and Bluetooth share one radio: scanning or pairing starves
    the sensors' Wi-Fi for its duration. Both are refused while recording, and
    the frames they cost are recorded as expected loss, not a sensor fault.
    """

    router = APIRouter(tags=["settings"])

    @contextmanager
    def bluetooth_radio_busy(reason: ExpectedFrameLoss) -> Iterator[None]:
        if run_recorder.enabled:
            raise HTTPException(status_code=409, detail=_RECORDING_ACTIVE_DETAIL[reason])
        with registry.expecting_frame_loss(reason), route_errors_to_http():
            yield

    @router.post(
        "/api/settings/obd/scan",
        response_model=ObdScanResponse,
        responses=_OBD_ADMIN_RESPONSES,
    )
    async def scan_obd_devices() -> ObdScanResponse:
        """Scan nearby Bluetooth OBD adapters (about 10 s; sensor data pauses meanwhile)."""

        with bluetooth_radio_busy("bluetooth_scan"):
            devices = await asyncio.to_thread(obd_admin_service.scan_obd_devices)
        return obd_scan_response(devices)

    @router.post(
        "/api/settings/obd/pair",
        response_model=ObdPairResponse,
        responses={400: {"description": "Invalid Bluetooth MAC address."}, **_OBD_ADMIN_RESPONSES},
    )
    async def pair_obd_device(req: ObdPairRequest) -> ObdPairResponse:
        """Pair, trust, connect, and persist the selected Bluetooth OBD adapter."""

        normalized_mac = normalize_mac_or_400(req.mac_address)
        with bluetooth_radio_busy("bluetooth_pairing"):
            device = await asyncio.to_thread(
                obd_admin_service.pair_obd_device,
                normalized_mac,
            )
        try:
            persisted = await asyncio.to_thread(
                speed_source_service.update_speed_source,
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
            await asyncio.to_thread(obd_admin_service.refresh_obd_status)
            snapshot = await asyncio.to_thread(speed_status_service.obd_status)
        return obd_status_response(snapshot)

    return router
