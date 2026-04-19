"""System update and ESP flash endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from vibesensor.adapters.http._helpers import OpenAPIResponses
from vibesensor.adapters.http.error_boundary import (
    http_exception_for_value_error,
    route_errors_to_http,
)
from vibesensor.adapters.http.models import (
    EspFlashCancelResponse,
    EspFlashHistoryResponse,
    EspFlashLogsResponse,
    EspFlashPortsResponse,
    EspFlashStartRequest,
    EspFlashStartResponse,
    EspFlashStatusResponse,
    UpdateCancelResponse,
    UpdateStartRequest,
    UpdateStartResponse,
    UpdateStatusResponse,
    UsbInternetStatusResponse,
)
from vibesensor.use_cases.updates.status import update_status_to_builtins

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
    from vibesensor.use_cases.updates.manager import UpdateManager

__all__ = ["create_update_routes"]

_UPDATE_START_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid Wi-Fi credentials or update request values."},
    409: {"description": "An update job is already running."},
    500: {"description": "The update process could not be started."},
}

_ESP_FLASH_START_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid flash settings or port selection."},
    409: {"description": "An ESP flash job is already running."},
    500: {"description": "The flash job could not be started."},
}


def create_update_routes(
    update_manager: UpdateManager,
    esp_flash_manager: EspFlashManager,
) -> APIRouter:
    """Create and return the OTA software/firmware update API routes."""
    router = APIRouter(tags=["updates"])

    # -- software update -------------------------------------------------------

    @router.get("/api/update/status", response_model=UpdateStatusResponse)
    async def get_update_status() -> UpdateStatusResponse:
        """Return the current OTA software update job state, logs, and runtime details."""
        return UpdateStatusResponse.model_validate(update_status_to_builtins(update_manager.status))

    @router.get("/api/update/internet-status", response_model=UsbInternetStatusResponse)
    async def get_usb_internet_status() -> UsbInternetStatusResponse:
        """Return the current USB internet detection and usability snapshot."""
        status = await update_manager.get_usb_internet_status()
        return UsbInternetStatusResponse.model_validate(
            {
                "detected": status.detected,
                "usable": status.usable,
                "interface_name": status.interface_name,
                "connection_name": status.connection_name,
                "driver": status.driver,
                "ipv4_addresses": list(status.ipv4_addresses),
                "gateway": status.gateway,
                "has_default_route": status.has_default_route,
                "diagnostic": status.diagnostic,
            }
        )

    @router.post(
        "/api/update/start",
        response_model=UpdateStartResponse,
        responses=_UPDATE_START_RESPONSES,
    )
    async def start_update(req: UpdateStartRequest) -> UpdateStartResponse:
        """Start an OTA software update using the supplied uplink Wi-Fi credentials."""
        try:
            with route_errors_to_http():
                update_manager.start(
                    ssid=req.ssid,
                    password=req.password,
                    transport=req.transport,
                )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        return UpdateStartResponse(
            status="started",
            transport=req.transport.value,
            ssid=req.ssid,
        )

    @router.post("/api/update/cancel", response_model=UpdateCancelResponse)
    async def cancel_update() -> UpdateCancelResponse:
        """Request cancellation of the active OTA software update job."""
        return UpdateCancelResponse(cancelled=update_manager.cancel())

    # -- ESP flash -------------------------------------------------------------

    @router.get("/api/esp-flash/ports", response_model=EspFlashPortsResponse)
    async def list_esp_flash_ports() -> EspFlashPortsResponse:
        """List serial ports currently available for ESP32 firmware flashing."""
        ports = await esp_flash_manager.list_ports()
        return EspFlashPortsResponse.model_validate({"ports": ports})

    @router.post(
        "/api/esp-flash/start",
        response_model=EspFlashStartResponse,
        responses=_ESP_FLASH_START_RESPONSES,
    )
    async def start_esp_flash(req: EspFlashStartRequest) -> EspFlashStartResponse:
        """Start a new ESP32 firmware flash job with either auto-detect or an explicit port."""
        with route_errors_to_http():
            job_id = esp_flash_manager.start(port=req.port, auto_detect=req.auto_detect)
        return EspFlashStartResponse(status="started", job_id=job_id)

    @router.get("/api/esp-flash/status", response_model=EspFlashStatusResponse)
    async def get_esp_flash_status() -> EspFlashStatusResponse:
        """Return the current ESP32 flash job state and the selected serial port, if any."""
        return EspFlashStatusResponse.model_validate(esp_flash_manager.status.to_dict())

    @router.get("/api/esp-flash/logs", response_model=EspFlashLogsResponse)
    async def get_esp_flash_logs(
        after: int = Query(
            default=0,
            ge=0,
            description="Return log lines strictly after this zero-based index.",
        ),
    ) -> EspFlashLogsResponse:
        """Return incremental ESP32 flash logs for polling clients."""
        return EspFlashLogsResponse.model_validate(esp_flash_manager.logs_since(after))

    @router.post("/api/esp-flash/cancel", response_model=EspFlashCancelResponse)
    async def cancel_esp_flash() -> EspFlashCancelResponse:
        """Request cancellation of the active ESP32 flash job."""
        return EspFlashCancelResponse(cancelled=esp_flash_manager.cancel())

    @router.get("/api/esp-flash/history", response_model=EspFlashHistoryResponse)
    async def get_esp_flash_history() -> EspFlashHistoryResponse:
        """List completed and failed ESP32 flash attempts kept in local history."""
        return EspFlashHistoryResponse.model_validate({"attempts": esp_flash_manager.history()})

    return router
