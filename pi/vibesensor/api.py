from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .constants import MPS_TO_KMH
from .locations import all_locations, label_for_code
from .protocol import client_id_mac, parse_client_id
from .reports import build_report_pdf, summarize_log

if TYPE_CHECKING:
    from .app import RuntimeState

LOGGER = logging.getLogger(__name__)


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class IdentifyRequest(BaseModel):
    duration_ms: int = Field(default=1500, ge=100, le=60_000)


class SetLocationRequest(BaseModel):
    location_code: str = Field(min_length=1, max_length=64)


class SpeedOverrideRequest(BaseModel):
    speed_kmh: float | None = Field(default=None, ge=0)


class AnalysisSettingsRequest(BaseModel):
    tire_width_mm: float | None = Field(default=None, gt=0)
    tire_aspect_pct: float | None = Field(default=None, gt=0)
    rim_in: float | None = Field(default=None, gt=0)
    final_drive_ratio: float | None = Field(default=None, gt=0)
    current_gear_ratio: float | None = Field(default=None, gt=0)
    wheel_bandwidth_pct: float | None = Field(default=None, gt=0)
    driveshaft_bandwidth_pct: float | None = Field(default=None, gt=0)
    engine_bandwidth_pct: float | None = Field(default=None, gt=0)
    speed_uncertainty_pct: float | None = Field(default=None, ge=0)
    tire_diameter_uncertainty_pct: float | None = Field(default=None, ge=0)
    final_drive_uncertainty_pct: float | None = Field(default=None, ge=0)
    gear_uncertainty_pct: float | None = Field(default=None, ge=0)
    min_abs_band_hz: float | None = Field(default=None, ge=0)
    max_band_half_width_pct: float | None = Field(default=None, gt=0)


def _log_dir(state: RuntimeState) -> Path:
    return state.config.logging.metrics_log_path.parent


def _normalize_client_id_or_400(client_id: str) -> str:
    try:
        return parse_client_id(client_id).hex()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid client_id") from exc


def _safe_log_path(state: RuntimeState, log_name: str) -> Path:
    candidate = Path(log_name).name
    if Path(candidate).suffix.lower() != ".jsonl":
        raise HTTPException(status_code=400, detail="Log name must be a .jsonl file")
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
    for path in sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
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

    @router.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @router.get("/api/clients")
    async def get_clients() -> dict:
        return {"clients": state.registry.snapshot_for_api()}

    @router.get("/api/client-locations")
    async def get_client_locations() -> dict:
        return {"locations": all_locations()}

    @router.get("/api/speed-override")
    async def get_speed_override() -> dict:
        override_mps = state.gps_monitor.override_speed_mps
        speed_kmh = (override_mps * MPS_TO_KMH) if isinstance(override_mps, (int, float)) else None
        return {"speed_kmh": speed_kmh}

    @router.post("/api/speed-override")
    async def set_speed_override(req: SpeedOverrideRequest) -> dict:
        speed_kmh = state.gps_monitor.set_speed_override_kmh(req.speed_kmh)
        return {"speed_kmh": speed_kmh}

    @router.get("/api/analysis-settings")
    async def get_analysis_settings() -> dict:
        return state.analysis_settings.snapshot()

    @router.post("/api/analysis-settings")
    async def set_analysis_settings(req: AnalysisSettingsRequest) -> dict:
        updated = state.analysis_settings.update(req.model_dump(exclude_none=True))
        return updated

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
        state.live_diagnostics.reset()
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
        return FileResponse(path, media_type="application/x-ndjson", filename=path.name)

    @router.delete("/api/logs/{log_name}")
    async def delete_log(log_name: str) -> dict:
        path = _safe_log_path(state, log_name)
        status = state.metrics_logger.status()
        active_file = status.get("current_file")
        if status.get("enabled") and isinstance(active_file, str) and active_file == path.name:
            raise HTTPException(status_code=409, detail="Cannot delete active log while logging")
        path.unlink()
        return {"name": path.name, "status": "deleted"}

    @router.get("/api/logs/{log_name}/insights")
    async def get_log_insights(
        log_name: str,
        lang: str | None = Query(default=None),
        include_samples: int = Query(default=0, ge=0, le=1),
    ) -> dict:
        path = _safe_log_path(state, log_name)
        try:
            return summarize_log(path, lang=lang, include_samples=bool(include_samples))
        except ValueError as exc:
            LOGGER.warning("Failed to summarize log '%s': %s", log_name, exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/logs/{log_name}/report.pdf")
    async def download_report_pdf(
        log_name: str, lang: str | None = Query(default=None)
    ) -> Response:
        path = _safe_log_path(state, log_name)
        try:
            summary = summarize_log(path, lang=lang, include_samples=True)
        except ValueError as exc:
            LOGGER.warning("Failed to build report PDF for '%s': %s", log_name, exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
                    LOGGER.debug("Ignoring malformed WS message (not valid JSON)")
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
