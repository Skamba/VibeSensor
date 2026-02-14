from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .app import RuntimeState


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class IdentifyRequest(BaseModel):
    duration_ms: int = Field(default=1500, ge=100, le=60_000)


def create_router(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/clients")
    async def get_clients() -> dict:
        return {"clients": state.registry.snapshot_for_api()}

    @router.post("/api/clients/{client_id}/rename")
    async def rename_client(client_id: str, req: RenameRequest) -> dict:
        target = state.registry.get(client_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Unknown client_id")
        try:
            updated = state.registry.set_name(client_id, req.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": updated.client_id, "name": updated.name}

    @router.post("/api/clients/{client_id}/identify")
    async def identify_client(client_id: str, req: IdentifyRequest) -> dict:
        ok, cmd_seq = state.control_plane.send_identify(client_id, req.duration_ms)
        if not ok:
            raise HTTPException(status_code=404, detail="Client missing or no control address")
        return {"status": "sent", "cmd_seq": cmd_seq}

    @router.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        selected = ws.query_params.get("client_id")
        await ws.accept()
        await state.ws_hub.add(ws, selected)
        try:
            while True:
                message = await ws.receive_text()
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and "client_id" in payload:
                    value = payload["client_id"]
                    if value is None:
                        await state.ws_hub.update_selected_client(ws, None)
                    elif isinstance(value, str) and len(value.replace(":", "")) == 12:
                        normalized = value.replace(":", "").lower()
                        await state.ws_hub.update_selected_client(ws, normalized)
        except WebSocketDisconnect:
            pass
        finally:
            await state.ws_hub.remove(ws)

    return router
