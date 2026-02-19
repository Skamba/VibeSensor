from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
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


class LanguageRequest(BaseModel):
    language: str = Field(pattern="^(en|nl)$")


class CarUpsertRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    aspects: dict[str, float] | None = None


class ActiveCarRequest(BaseModel):
    carId: str = Field(min_length=1)


class SpeedSourceRequest(BaseModel):
    speedSource: str | None = None
    manualSpeedKph: float | None = None
    obd2Config: dict[str, object] | None = None


class SensorRequest(BaseModel):
    name: str | None = None
    location: str | None = None


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

    def _analysis_language(run: dict, requested: str | None) -> str:
        if isinstance(requested, str) and requested.strip():
            return requested.strip().lower()
        metadata = run.get("metadata", {})
        if isinstance(metadata, dict):
            value = metadata.get("language")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return "en"

    def _iter_normalized_samples(run_id: str, *, batch_size: int = 1000) -> Iterator[dict]:
        from .runlog import normalize_sample_record

        for batch in state.history_db.iter_run_samples(run_id, batch_size=batch_size):
            for sample in batch:
                yield normalize_sample_record(sample)

    @router.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "processing_state": state.processing_state,
            "processing_failures": state.processing_failure_count,
        }

    # -- new settings endpoints (3-tab model) ----------------------------------

    @router.get("/api/settings")
    async def get_settings() -> dict:
        return state.settings_store.snapshot()

    @router.get("/api/settings/cars")
    async def get_cars() -> dict:
        return state.settings_store.get_cars()

    @router.post("/api/settings/cars")
    async def add_car(req: CarUpsertRequest) -> dict:
        result = state.settings_store.add_car(req.model_dump(exclude_none=True))
        _sync_active_car_to_analysis(state)
        return result

    @router.put("/api/settings/cars/{car_id}")
    async def update_car(car_id: str, req: CarUpsertRequest) -> dict:
        try:
            result = state.settings_store.update_car(car_id, req.model_dump(exclude_none=True))
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
    async def set_active_car(req: ActiveCarRequest) -> dict:
        car_id = req.carId
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
    async def update_speed_source(req: SpeedSourceRequest) -> dict:
        result = state.settings_store.update_speed_source(req.model_dump(exclude_none=True))
        _sync_speed_source_to_gps(state)
        return result

    @router.get("/api/settings/sensors")
    async def get_sensors() -> dict:
        return {"sensorsByMac": state.settings_store.get_sensors()}

    @router.post("/api/settings/sensors/{mac}")
    async def update_sensor(mac: str, req: SensorRequest) -> dict:
        try:
            state.settings_store.set_sensor(mac, req.model_dump(exclude_none=True))
            return {"sensorsByMac": state.settings_store.get_sensors()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/settings/sensors/{mac}")
    async def delete_sensor(mac: str) -> dict:
        try:
            removed = state.settings_store.remove_sensor(mac)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown sensor MAC")
        return {"sensorsByMac": state.settings_store.get_sensors()}

    @router.get("/api/settings/language")
    async def get_language() -> dict:
        return {"language": state.settings_store.language}

    @router.post("/api/settings/language")
    async def set_language(req: LanguageRequest) -> dict:
        try:
            language = state.settings_store.set_language(req.language)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"language": language}

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
        metadata = run.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        language = _analysis_language(run, lang)
        samples = list(_iter_normalized_samples(run_id, batch_size=1024))
        return summarize_run_data(
            metadata,
            samples,
            lang=language,
            file_name=run_id,
            include_samples=False,
        )

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
        metadata = run.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        samples = list(_iter_normalized_samples(run_id, batch_size=2048))
        if len(samples) > 12_000:
            stride = max(1, len(samples) // 12_000)
            samples = samples[::stride]
        try:
            report_model = summarize_run_data(
                metadata,
                samples,
                lang=_analysis_language(run, lang),
                file_name=run_id,
                include_samples=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        pdf = build_report_pdf(report_model)
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

        def _stream() -> Iterator[bytes]:
            yield (json.dumps(metadata, ensure_ascii=True) + "\n").encode("utf-8")
            for batch in state.history_db.iter_run_samples(run_id, batch_size=2048):
                for sample in batch:
                    yield (json.dumps(sample, ensure_ascii=True) + "\n").encode("utf-8")

        return StreamingResponse(
            _stream(),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.jsonl"'},
        )

    @router.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        selected = ws.query_params.get("client_id")
        if selected is not None:
            try:
                selected = parse_client_id(selected).hex()
            except ValueError:
                selected = None
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
                    elif isinstance(value, str):
                        try:
                            normalized = parse_client_id(value).hex()
                        except ValueError:
                            continue
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
