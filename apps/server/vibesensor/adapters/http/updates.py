"""System update and ESP flash endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from vibesensor.adapters.http._helpers import domain_errors_to_http
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
)

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.esp_flash_manager import EspFlashManager
    from vibesensor.use_cases.updates.manager import UpdateManager

__all__ = ["create_update_routes"]


def create_update_routes(
    update_manager: UpdateManager,
    esp_flash_manager: EspFlashManager,
) -> APIRouter:
    """Create and return the OTA software/firmware update API routes."""
    router = APIRouter()

    # -- software update -------------------------------------------------------

    @router.get("/api/update/status", response_model=UpdateStatusResponse)
    async def get_update_status() -> UpdateStatusResponse:
        return UpdateStatusResponse.model_validate(update_manager.status.to_payload())

    @router.post("/api/update/start", response_model=UpdateStartResponse)
    async def start_update(req: UpdateStartRequest) -> UpdateStartResponse:
        with domain_errors_to_http(catch_value_error=400, catch_runtime_error=409):
            update_manager.start(req.ssid, req.password)
        return UpdateStartResponse(status="started", ssid=req.ssid)

    @router.post("/api/update/cancel", response_model=UpdateCancelResponse)
    async def cancel_update() -> UpdateCancelResponse:
        return UpdateCancelResponse(cancelled=update_manager.cancel())

    # -- ESP flash -------------------------------------------------------------

    @router.get("/api/esp-flash/ports", response_model=EspFlashPortsResponse)
    async def list_esp_flash_ports() -> EspFlashPortsResponse:
        ports = await esp_flash_manager.list_ports()
        return EspFlashPortsResponse.model_validate({"ports": ports})

    @router.post("/api/esp-flash/start", response_model=EspFlashStartResponse)
    async def start_esp_flash(req: EspFlashStartRequest) -> EspFlashStartResponse:
        with domain_errors_to_http(catch_value_error=400, catch_runtime_error=409):
            job_id = esp_flash_manager.start(port=req.port, auto_detect=req.auto_detect)
        return EspFlashStartResponse(status="started", job_id=job_id)

    @router.get("/api/esp-flash/status", response_model=EspFlashStatusResponse)
    async def get_esp_flash_status() -> EspFlashStatusResponse:
        return EspFlashStatusResponse.model_validate(esp_flash_manager.status.to_dict())

    @router.get("/api/esp-flash/logs", response_model=EspFlashLogsResponse)
    async def get_esp_flash_logs(after: int = Query(default=0, ge=0)) -> EspFlashLogsResponse:
        return EspFlashLogsResponse.model_validate(esp_flash_manager.logs_since(after))

    @router.post("/api/esp-flash/cancel", response_model=EspFlashCancelResponse)
    async def cancel_esp_flash() -> EspFlashCancelResponse:
        return EspFlashCancelResponse(cancelled=esp_flash_manager.cancel())

    @router.get("/api/esp-flash/history", response_model=EspFlashHistoryResponse)
    async def get_esp_flash_history() -> EspFlashHistoryResponse:
        return EspFlashHistoryResponse.model_validate({"attempts": esp_flash_manager.history()})

    return router
