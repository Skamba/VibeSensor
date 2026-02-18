from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .constants import MPS_TO_KMH
from .locations import all_locations, label_for_code
from .protocol import client_id_mac, parse_client_id
from .reports import build_report_pdf, summarize_run_data

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


def _normalize_client_id_or_400(client_id: str) -> str:
    try:
        return parse_client_id(client_id).hex()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid client_id") from exc


def _sync_active_car_to_analysis(state: RuntimeState) -> None:
    """Push active car aspects into the shared AnalysisSettingsStore."""
    aspects = state.settings_store.active_car_aspects()
    state.analysis_settings.update(aspects)


def _sync_speed_source_to_gps(state: RuntimeState) -> None:
    """Push speed-source settings into GPSSpeedMonitor."""
    ss = state.settings_store.get_speed_source()
    if ss["speedSource"] == "manual" and ss["manualSpeedKph"] is not None:
        state.gps_monitor.set_speed_override_kmh(ss["manualSpeedKph"])
    else:
        state.gps_monitor.set_speed_override_kmh(None)


def create_router(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    # -- new settings endpoints (3-tab model) ----------------------------------

    @router.get("/api/settings")
    async def get_settings() -> dict:
        return state.settings_store.snapshot()

    @router.get("/api/settings/cars")
    async def get_cars() -> dict:
        return state.settings_store.get_cars()

    @router.post("/api/settings/cars")
    async def add_car(req: dict) -> dict:
        result = state.settings_store.add_car(req)
        _sync_active_car_to_analysis(state)
        return result

    @router.put("/api/settings/cars/{car_id}")
    async def update_car(car_id: str, req: dict) -> dict:
        try:
            result = state.settings_store.update_car(car_id, req)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _sync_active_car_to_analysis(state)
        return result

    @router.delete("/api/settings/cars/{car_id}")
    async def delete_car(car_id: str) -> dict:
        try:
            result = state.settings_store.delete_car(car_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _sync_active_car_to_analysis(state)
        return result

    @router.post("/api/settings/cars/active")
    async def set_active_car(req: dict) -> dict:
        car_id = req.get("carId", "")
        try:
            result = state.settings_store.set_active_car(car_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _sync_active_car_to_analysis(state)
        return result

    @router.get("/api/settings/speed-source")
    async def get_speed_source() -> dict:
        return state.settings_store.get_speed_source()

    @router.post("/api/settings/speed-source")
    async def update_speed_source(req: dict) -> dict:
        result = state.settings_store.update_speed_source(req)
        _sync_speed_source_to_gps(state)
        return result

    @router.get("/api/settings/sensors")
    async def get_sensors() -> dict:
        return {"sensorsByMac": state.settings_store.get_sensors()}

    @router.post("/api/settings/sensors/{mac}")
    async def update_sensor(mac: str, req: dict) -> dict:
        return state.settings_store.set_sensor(mac, req)

    @router.delete("/api/settings/sensors/{mac}")
    async def delete_sensor(mac: str) -> dict:
        removed = state.settings_store.remove_sensor(mac)
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown sensor MAC")
        return {"mac": mac, "status": "removed"}

    # -- legacy endpoints (adapters) -------------------------------------------

    @router.get("/api/clients")
    async def get_clients() -> dict:
        return {"clients": state.registry.snapshot_for_api()}

    @router.get("/api/client-locations")
    async def get_client_locations() -> dict:
        return {"locations": all_locations()}

    @router.get("/api/speed-override")
    async def get_speed_override() -> dict:
        ss = state.settings_store.get_speed_source()
        if ss["speedSource"] == "manual" and ss["manualSpeedKph"] is not None:
            return {"speed_kmh": ss["manualSpeedKph"]}
        override_mps = state.gps_monitor.override_speed_mps
        speed_kmh = (override_mps * MPS_TO_KMH) if isinstance(override_mps, (int, float)) else None
        return {"speed_kmh": speed_kmh}

    @router.post("/api/speed-override")
    async def set_speed_override(req: SpeedOverrideRequest) -> dict:
        if req.speed_kmh is not None and req.speed_kmh > 0:
            state.settings_store.update_speed_source(
                {"speedSource": "manual", "manualSpeedKph": req.speed_kmh}
            )
        else:
            state.settings_store.update_speed_source({"speedSource": "gps", "manualSpeedKph": None})
        _sync_speed_source_to_gps(state)
        override_mps = state.gps_monitor.override_speed_mps
        speed_kmh = (override_mps * MPS_TO_KMH) if isinstance(override_mps, (int, float)) else None
        return {"speed_kmh": speed_kmh}

    @router.post("/api/simulator/speed-override")
    async def set_simulator_speed_override(req: SpeedOverrideRequest) -> dict:
        return await set_speed_override(req)

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
        mac = client_id_mac(updated.client_id)
        state.settings_store.set_sensor(mac, {"name": req.name})
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
        mac = client_id_mac(updated.client_id)
        state.settings_store.set_sensor(mac, {"location": req.location_code})
        return {
            "id": updated.client_id,
            "mac_address": mac,
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

    @router.get("/api/history")
    async def get_history() -> dict:
        return {"runs": state.history_db.list_runs()}

    @router.get("/api/history/{run_id}")
    async def get_history_run(run_id: str) -> dict:
        run = state.history_db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @router.get("/api/history/{run_id}/insights")
    async def get_history_insights(
        run_id: str,
        lang: str | None = Query(default=None),
    ) -> dict:
        run = state.history_db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if run["status"] == "analyzing":
            return {"run_id": run_id, "status": "analyzing"}
        if run["status"] == "error":
            raise HTTPException(status_code=422, detail=run.get("error_message", "Analysis failed"))
        analysis = run.get("analysis")
        if analysis is None:
            raise HTTPException(status_code=422, detail="No analysis available for this run")
        return analysis

    @router.delete("/api/history/{run_id}")
    async def delete_history_run(run_id: str) -> dict:
        active_run_id = state.history_db.get_active_run_id()
        if active_run_id == run_id:
            raise HTTPException(
                status_code=409, detail="Cannot delete the active run; stop recording first"
            )
        deleted = state.history_db.delete_run(run_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"run_id": run_id, "status": "deleted"}

    @router.get("/api/history/{run_id}/report.pdf")
    async def download_history_report_pdf(
        run_id: str, lang: str | None = Query(default=None)
    ) -> Response:
        run = state.history_db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        analysis = run.get("analysis")
        if analysis is None:
            raise HTTPException(status_code=422, detail="No analysis available for this run")
        # Re-attach samples for plots/PDF generation if not present
        if "samples" not in analysis or not analysis["samples"]:
            from .runlog import normalize_sample_record

            raw_samples = state.history_db.get_run_samples(run_id)
            analysis["samples"] = [normalize_sample_record(s) for s in raw_samples]
            # Recompute full summary from stored data for the requested language
            metadata = run.get("metadata", {})
            try:
                analysis = summarize_run_data(
                    metadata,
                    analysis["samples"],
                    lang=lang,
                    file_name=run_id,
                    include_samples=True,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        pdf = build_report_pdf(analysis)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{run_id}_report.pdf"'},
        )

    @router.get("/api/history/{run_id}/export")
    async def export_history_run(run_id: str) -> Response:
        run = state.history_db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        metadata = run.get("metadata", {})
        samples = state.history_db.get_run_samples(run_id)
        lines: list[str] = []
        lines.append(json.dumps(metadata, ensure_ascii=True))
        for s in samples:
            lines.append(json.dumps(s, ensure_ascii=True))
        content = "\n".join(lines) + "\n"
        return Response(
            content=content,
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.jsonl"'},
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
            LOGGER.debug("WebSocket client disconnected")
        finally:
            await state.ws_hub.remove(ws)

    @router.get("/api/car-library")
    async def get_car_library() -> dict:
        from .car_library import CAR_LIBRARY

        return {"cars": CAR_LIBRARY}

    @router.get("/api/car-library/brands")
    async def get_car_library_brands() -> dict:
        from .car_library import get_brands

        return {"brands": get_brands()}

    @router.get("/api/car-library/types")
    async def get_car_library_types(brand: str = Query(...)) -> dict:
        from .car_library import get_types_for_brand

        return {"types": get_types_for_brand(brand)}

    @router.get("/api/car-library/models")
    async def get_car_library_models(
        brand: str = Query(...), car_type: str = Query(..., alias="type")
    ) -> dict:
        from .car_library import get_models_for_brand_type

        return {"models": get_models_for_brand_type(brand, car_type)}

    @router.get("/api/debug/spectrum/{client_id}")
    async def debug_spectrum(client_id: str) -> dict:
        """Detailed spectrum debug info for independent verification."""
        normalized = _normalize_client_id_or_400(client_id)
        return state.processor.debug_spectrum(normalized)

    @router.get("/api/debug/raw-samples/{client_id}")
    async def debug_raw_samples(
        client_id: str,
        n: int = Query(default=2048, ge=1, le=6400),
    ) -> dict:
        """Raw time-domain samples in g for offline analysis."""
        normalized = _normalize_client_id_or_400(client_id)
        return state.processor.raw_samples(normalized, n_samples=n)

    return router
