"""System update and ESP flash endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from ..api_models import (
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
    from ..app import RuntimeState


def create_update_routes(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    # -- software update -------------------------------------------------------

    @router.get("/api/settings/update/status", response_model=UpdateStatusResponse)
    async def get_update_status() -> UpdateStatusResponse:
        return state.update_manager.status.to_dict()

    @router.post("/api/settings/update/start", response_model=UpdateStartResponse)
    async def start_update(req: UpdateStartRequest) -> UpdateStartResponse:
        try:
            state.update_manager.start(req.ssid, req.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "started", "ssid": req.ssid}

    @router.post("/api/settings/update/cancel", response_model=UpdateCancelResponse)
    async def cancel_update() -> UpdateCancelResponse:
        cancelled = state.update_manager.cancel()
        return {"cancelled": cancelled}

    # -- ESP flash -------------------------------------------------------------

    @router.get("/api/settings/esp-flash/ports", response_model=EspFlashPortsResponse)
    async def list_esp_flash_ports() -> EspFlashPortsResponse:
        ports = await state.esp_flash_manager.list_ports()
        return {"ports": ports}

    @router.post("/api/settings/esp-flash/start", response_model=EspFlashStartResponse)
    async def start_esp_flash(req: EspFlashStartRequest) -> EspFlashStartResponse:
        try:
            job_id = state.esp_flash_manager.start(port=req.port, auto_detect=req.auto_detect)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "started", "job_id": job_id}

    @router.get("/api/settings/esp-flash/status", response_model=EspFlashStatusResponse)
    async def get_esp_flash_status() -> EspFlashStatusResponse:
        return state.esp_flash_manager.status.to_dict()

    @router.get("/api/settings/esp-flash/logs", response_model=EspFlashLogsResponse)
    async def get_esp_flash_logs(after: int = Query(default=0, ge=0)) -> EspFlashLogsResponse:
        return state.esp_flash_manager.logs_since(after)

    @router.post("/api/settings/esp-flash/cancel", response_model=EspFlashCancelResponse)
    async def cancel_esp_flash() -> EspFlashCancelResponse:
        return {"cancelled": state.esp_flash_manager.cancel()}

    @router.get("/api/settings/esp-flash/history", response_model=EspFlashHistoryResponse)
    async def get_esp_flash_history() -> EspFlashHistoryResponse:
        return {"attempts": state.esp_flash_manager.history()}

    return router
