from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .locations import all_locations, label_for_code
from .protocol import client_id_mac, parse_client_id
from .reports import build_report_pdf, summarize_log

if TYPE_CHECKING:
    from .app import RuntimeState


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class IdentifyRequest(BaseModel):
    duration_ms: int = Field(default=1500, ge=100, le=60_000)


class SetLocationRequest(BaseModel):
    location_code: str = Field(min_length=1, max_length=64)


def _log_dir(state: RuntimeState) -> Path:
    return state.config.logging.metrics_csv_path.parent


def _normalize_client_id_or_400(client_id: str) -> str:
    try:
        return parse_client_id(client_id).hex()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid client_id") from exc


def _safe_log_path(state: RuntimeState, log_name: str) -> Path:
    candidate = Path(log_name).name
    if not candidate.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Log name must be a .csv file")
    path = (_log_dir(state) / candidate).resolve()
    try:
        path.relative_to(_log_dir(state).resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid log path") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    return path


def _list_logs(state: RuntimeState) -> list[dict]:
    out: list[dict] = []
    log_dir = _log_dir(state)
    if not log_dir.exists():
        return out
    for path in sorted(log_dir.glob("*.csv"), reverse=True):
        stat = path.stat()
        out.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            }
        )
    return out


def create_router(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/clients")
    async def get_clients() -> dict:
        return {"clients": state.registry.snapshot_for_api()}

    @router.get("/api/client-locations")
    async def get_client_locations() -> dict:
        return {"locations": all_locations()}

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

    @router.post("/api/clients/{client_id}/location")
    async def set_client_location(client_id: str, req: SetLocationRequest) -> dict:
        normalized_client_id = _normalize_client_id_or_400(client_id)

        label = label_for_code(req.location_code)
        if label is None:
            raise HTTPException(status_code=400, detail="Unknown location_code")

        for row in state.registry.snapshot_for_api():
            if row["id"] != normalized_client_id and row["name"] == label:
                raise HTTPException(
                    status_code=409,
                    detail=f"Location already assigned to client {row['id']}",
                )

        updated = state.registry.set_name(normalized_client_id, label)
        return {
            "id": updated.client_id,
            "mac_address": client_id_mac(updated.client_id),
            "location_code": req.location_code,
            "name": updated.name,
        }

    @router.delete("/api/clients/{client_id}")
    async def remove_client(client_id: str) -> dict:
        normalized_client_id = _normalize_client_id_or_400(client_id)
        removed = state.registry.remove_client(normalized_client_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown client_id")
        return {"id": normalized_client_id, "status": "removed"}

    @router.get("/api/logging/status")
    async def get_logging_status() -> dict:
        return state.metrics_logger.status()

    @router.post("/api/logging/start")
    async def start_logging() -> dict:
        return state.metrics_logger.start_logging()

    @router.post("/api/logging/stop")
    async def stop_logging() -> dict:
        return state.metrics_logger.stop_logging()

    @router.get("/api/logs")
    async def get_logs() -> dict:
        return {"logs": _list_logs(state)}

    @router.get("/api/logs/{log_name}")
    async def download_log(log_name: str) -> FileResponse:
        path = _safe_log_path(state, log_name)
        return FileResponse(path, media_type="text/csv", filename=path.name)

    @router.get("/api/logs/{log_name}/insights")
    async def get_log_insights(log_name: str) -> dict:
        path = _safe_log_path(state, log_name)
        return summarize_log(path)

    @router.get("/api/logs/{log_name}/report.pdf")
    async def download_report_pdf(log_name: str) -> Response:
        path = _safe_log_path(state, log_name)
        summary = summarize_log(path)
        pdf = build_report_pdf(summary)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{path.stem}_report.pdf"'},
        )

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
