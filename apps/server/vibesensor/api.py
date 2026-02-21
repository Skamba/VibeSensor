from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import zipfile
from collections.abc import Iterator
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .locations import all_locations, label_for_code
from .protocol import client_id_mac, parse_client_id
from .report.pdf_builder import build_report_pdf
from .report.summary import summarize_run_data

if TYPE_CHECKING:
    from .app import RuntimeState

LOGGER = logging.getLogger(__name__)
_MAX_REPORT_SAMPLES = 12_000


def _bounded_sample(
    samples: Iterator[dict],
    *,
    max_items: int,
    total_hint: int = 0,
) -> tuple[list[dict], int, int]:
    """Down-sample *samples* to at most *max_items*.

    When *total_hint* is available the stride is computed upfront so
    that we never over-collect and re-halve.
    """
    stride: int = max(1, total_hint // max_items) if total_hint > max_items else 1
    kept: list[dict] = []
    total = 0
    for sample in samples:
        total += 1
        if (total - 1) % stride != 0:
            continue
        kept.append(sample)
        if len(kept) > max_items:
            kept = kept[::2]
            stride *= 2
    return kept, total, stride


class IdentifyRequest(BaseModel):
    duration_ms: int = Field(default=1500, ge=100, le=60_000)


class SetLocationRequest(BaseModel):
    location_code: str = Field(min_length=1, max_length=64)


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


class SpeedUnitRequest(BaseModel):
    speedUnit: str = Field(pattern="^(kmh|mps)$")


class CarUpsertRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    aspects: dict[str, float] | None = None


class ActiveCarRequest(BaseModel):
    carId: str = Field(min_length=1)


class SpeedSourceRequest(BaseModel):
    speedSource: str | None = None
    manualSpeedKph: float | None = None
    staleTimeoutS: float | None = None
    fallbackMode: str | None = None


class UpdateStartRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=128)


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
    state.gps_monitor.set_fallback_settings(
        stale_timeout_s=ss.get("staleTimeoutS"),
        fallback_mode=ss.get("fallbackMode"),
    )


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

    @router.get("/api/settings/speed-source/status")
    async def get_speed_source_status() -> dict:
        return state.gps_monitor.status_dict()

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

    @router.get("/api/settings/speed-unit")
    async def get_speed_unit() -> dict:
        return {"speedUnit": state.settings_store.speed_unit}

    @router.post("/api/settings/speed-unit")
    async def set_speed_unit(req: SpeedUnitRequest) -> dict:
        try:
            unit = state.settings_store.set_speed_unit(req.speedUnit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"speedUnit": unit}

    # -- client & location endpoints -------------------------------------------

    @router.get("/api/clients")
    async def get_clients() -> dict:
        return {"clients": state.registry.snapshot_for_api()}

    @router.get("/api/client-locations")
    async def get_client_locations() -> dict:
        return {"locations": all_locations()}

    @router.post("/api/simulator/speed-override")
    async def set_simulator_speed_override(req: SpeedSourceRequest) -> dict:
        return await update_speed_source(req)

    @router.get("/api/analysis-settings")
    async def get_analysis_settings() -> dict:
        return state.analysis_settings.snapshot()

    @router.post("/api/analysis-settings")
    async def set_analysis_settings(req: AnalysisSettingsRequest) -> dict:
        changes = req.model_dump(exclude_none=True)
        if changes:
            state.settings_store.update_active_car_aspects(changes)
            _sync_active_car_to_analysis(state)
        return state.analysis_settings.snapshot()

    @router.post("/api/clients/{client_id}/identify")
    async def identify_client(client_id: str, req: IdentifyRequest) -> dict:
        ok, cmd_seq = state.control_plane.send_identify(client_id, req.duration_ms)
        if not ok:
            raise HTTPException(status_code=404, detail="Client missing or no control address")
        return {"status": "sent", "cmd_seq": cmd_seq}

    @router.post("/api/clients/{client_id}/location")
    async def set_client_location(client_id: str, req: SetLocationRequest) -> dict:
        normalized_client_id = _normalize_client_id_or_400(client_id)
        if state.registry.get(normalized_client_id) is None:
            raise HTTPException(status_code=404, detail="Unknown client_id")

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
        if lang is not None:

            def _recompute() -> dict:
                from .runlog import normalize_sample_record

                normalized_iter = (
                    normalize_sample_record(sample)
                    for batch in state.history_db.iter_run_samples(run_id)
                    for sample in batch
                )
                samples, total_samples, stride = _bounded_sample(
                    normalized_iter,
                    max_items=_MAX_REPORT_SAMPLES,
                )
                metadata = run.get("metadata", {})
                result = summarize_run_data(
                    metadata,
                    samples,
                    lang=lang,
                    file_name=run_id,
                    include_samples=False,
                )
                if stride > 1 and isinstance(result, dict):
                    result["sampling"] = {
                        "total_samples": total_samples,
                        "analyzed_samples": len(samples),
                        "method": f"stride_{stride}",
                    }
                return result

            try:
                analysis = await asyncio.to_thread(_recompute)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
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
        metadata = run.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        requested_lang = _analysis_language(run, lang)

        def _build_pdf() -> tuple[bytes, int, int, int]:
            from .report.plot_data import _plot_data

            samples, total_samples, stride = _bounded_sample(
                _iter_normalized_samples(run_id, batch_size=2048),
                max_items=_MAX_REPORT_SAMPLES,
            )
            persisted_lang = str(analysis.get("lang") or "en")
            if persisted_lang == requested_lang:
                # Reuse persisted analysis; only recompute plot data from samples
                report_model = dict(analysis)
                report_model["samples"] = samples
                report_model["plots"] = _plot_data(report_model)
            else:
                # Language differs from persisted analysis – full recompute needed
                report_model = summarize_run_data(
                    metadata,
                    samples,
                    lang=requested_lang,
                    file_name=run_id,
                    include_samples=True,
                )
            pdf = build_report_pdf(report_model)
            return pdf, total_samples, len(samples), stride

        pdf, total_samples, analyzed, stride = await asyncio.to_thread(_build_pdf)
        if stride > 1:
            LOGGER.info(
                "PDF report sample downsampling applied for run %s: total=%d analyzed=%d stride=%d",
                run_id,
                total_samples,
                analyzed,
                stride,
            )
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

        def _build_zip() -> bytes:
            fieldnames: list[str] = []
            fieldname_set: set[str] = set()
            # First pass: collect all unique field names and count samples
            sample_count = 0
            for batch in state.history_db.iter_run_samples(run_id, batch_size=2048):
                for sample in batch:
                    sample_count += 1
                    for key in sample:
                        if key not in fieldname_set:
                            fieldname_set.add(key)
                            fieldnames.append(key)

            # Second pass: write CSV rows batch by batch with known field names
            csv_buffer = io.StringIO(newline="")
            if fieldnames:
                writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
                writer.writeheader()
                for batch in state.history_db.iter_run_samples(run_id, batch_size=2048):
                    writer.writerows(batch)

            run_details = dict(run)
            run_details["sample_count"] = sample_count

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    f"{run_id}.json",
                    json.dumps(run_details, ensure_ascii=False, indent=2, sort_keys=True),
                )
                archive.writestr(f"{run_id}_raw.csv", csv_buffer.getvalue())
            return zip_buffer.getvalue()

        content = await asyncio.to_thread(_build_zip)
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
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

    # -- system update endpoints -----------------------------------------------

    @router.get("/api/settings/update/status")
    async def get_update_status() -> dict:
        return state.update_manager.status.to_dict()

    @router.post("/api/settings/update/start")
    async def start_update(req: UpdateStartRequest) -> dict:
        try:
            state.update_manager.start(req.ssid, req.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "started", "ssid": req.ssid}

    @router.post("/api/settings/update/cancel")
    async def cancel_update() -> dict:
        cancelled = state.update_manager.cancel()
        return {"cancelled": cancelled}

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
