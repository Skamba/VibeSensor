from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import zipfile
from collections import OrderedDict
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from .analysis import summarize_run_data
from .api_models import (  # noqa: F401
    ActiveCarRequest,
    AnalysisSettingsRequest,
    AnalysisSettingsResponse,
    CarLibraryBrandsResponse,
    CarLibraryGearboxEntry,
    CarLibraryModelEntry,
    CarLibraryModelsResponse,
    CarLibraryTireOptionEntry,
    CarLibraryTypesResponse,
    CarLibraryVariantEntry,
    CarResponse,
    CarsResponse,
    CarUpsertRequest,
    ClientLocationsResponse,
    ClientsResponse,
    DeleteHistoryRunResponse,
    EspFlashCancelResponse,
    EspFlashHistoryResponse,
    EspFlashLogsResponse,
    EspFlashPortsResponse,
    EspFlashStartRequest,
    EspFlashStartResponse,
    EspFlashStatusResponse,
    HealthResponse,
    HistoryInsightsResponse,
    HistoryListResponse,
    HistoryRunResponse,
    IdentifyRequest,
    IdentifyResponse,
    LanguageRequest,
    LanguageResponse,
    LocationOptionResponse,
    LoggingStatusResponse,
    RemoveClientResponse,
    SensorConfigResponse,
    SensorRequest,
    SensorsResponse,
    SetClientLocationResponse,
    SetLocationRequest,
    SpeedSourceRequest,
    SpeedSourceResponse,
    SpeedSourceStatusResponse,
    SpeedUnitRequest,
    SpeedUnitResponse,
    UpdateCancelResponse,
    UpdateIssueResponse,
    UpdateStartRequest,
    UpdateStartResponse,
    UpdateStatusResponse,
)
from .locations import all_locations, label_for_code
from .protocol import client_id_mac, parse_client_id
from .report.pdf_builder import build_report_pdf
from .runlog import bounded_sample as _bounded_sample

if TYPE_CHECKING:
    from .app import RuntimeState
    from .report.report_data import ReportTemplateData

LOGGER = logging.getLogger(__name__)
_MAX_REPORT_SAMPLES = 12_000
_EXPORT_BATCH_SIZE = 2048
_REPORT_PDF_CACHE_MAX_ENTRIES = 16
_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


def _flatten_for_csv(row: dict[str, Any]) -> dict[str, Any]:
    """Convert nested/complex values to JSON strings for CSV export.

    ``csv.DictWriter`` calls ``str()`` on values, which produces Python
    repr for dicts/lists (single-quoted keys, etc.).  Serializing them as
    JSON ensures the output is parseable by non-Python consumers.
    """
    return {
        k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        for k, v in row.items()
    }


def _safe_filename(name: str) -> str:
    """Sanitize *name* for use in Content-Disposition headers and zip entry names."""
    return _SAFE_FILENAME_RE.sub("_", name)[:200] or "download"


def _reconstruct_report_template_data(d: dict) -> ReportTemplateData:
    """Reconstruct a :class:`ReportTemplateData` from a persisted dict."""
    from .report.report_data import (
        CarMeta,
        DataTrustItem,
        NextStep,
        ObservedSignature,
        PartSuggestion,
        PatternEvidence,
        PeakRow,
        ReportTemplateData,
        SystemFindingCard,
    )

    car = d.get("car") or {}
    obs = d.get("observed") or {}
    pe = d.get("pattern_evidence") or {}
    return ReportTemplateData(
        title=d.get("title", ""),
        run_datetime=d.get("run_datetime"),
        run_id=d.get("run_id"),
        duration_text=d.get("duration_text"),
        start_time_utc=d.get("start_time_utc"),
        end_time_utc=d.get("end_time_utc"),
        sample_rate_hz=d.get("sample_rate_hz"),
        tire_spec_text=d.get("tire_spec_text"),
        sample_count=d.get("sample_count", 0),
        sensor_count=d.get("sensor_count", 0),
        sensor_locations=d.get("sensor_locations", []),
        sensor_model=d.get("sensor_model"),
        firmware_version=d.get("firmware_version"),
        car=CarMeta(**car) if isinstance(car, dict) else CarMeta(),
        observed=ObservedSignature(**obs) if isinstance(obs, dict) else ObservedSignature(),
        system_cards=[
            SystemFindingCard(
                **{
                    **c,
                    "parts": [
                        PartSuggestion(**p) if isinstance(p, dict) else PartSuggestion(name=str(p))
                        for p in (c.get("parts") or [])
                    ],
                }
            )
            for c in d.get("system_cards", [])
            if isinstance(c, dict)
        ],
        next_steps=[NextStep(**s) for s in d.get("next_steps", []) if isinstance(s, dict)],
        data_trust=[DataTrustItem(**t) for t in d.get("data_trust", []) if isinstance(t, dict)],
        pattern_evidence=(PatternEvidence(**pe) if isinstance(pe, dict) else PatternEvidence()),
        peak_rows=[PeakRow(**r) for r in d.get("peak_rows", []) if isinstance(r, dict)],
        phase_info=d.get("phase_info"),
        version_marker=d.get("version_marker", ""),
        lang=d.get("lang", "en"),
        certainty_tier_key=d.get("certainty_tier_key", "C"),
        findings=d.get("findings", []),
        top_causes=d.get("top_causes", []),
        sensor_intensity_by_location=d.get("sensor_intensity_by_location", []),
        location_hotspot_rows=d.get("location_hotspot_rows", []),
    )


def _normalize_client_id_or_400(client_id: str) -> str:
    try:
        return parse_client_id(client_id).hex()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid client_id") from exc


def create_router(state: RuntimeState) -> APIRouter:
    router = APIRouter()
    report_pdf_cache: OrderedDict[tuple[object, ...], bytes] = OrderedDict()
    report_pdf_locks: dict[tuple[object, ...], asyncio.Lock] = {}

    def _metadata_cache_token(metadata: object) -> str:
        if not isinstance(metadata, dict):
            return "{}"
        return json.dumps(metadata, sort_keys=True, default=str, ensure_ascii=False)

    def _report_pdf_cache_key(
        run: dict[str, Any], run_id: str, requested_lang: str
    ) -> tuple[object, ...]:
        return (
            run_id,
            requested_lang,
            run.get("analysis_version"),
            run.get("analysis_completed_at"),
            run.get("sample_count"),
            _metadata_cache_token(run.get("metadata", {})),
        )

    def _cache_get(cache_key: tuple[object, ...]) -> bytes | None:
        cached_pdf = report_pdf_cache.get(cache_key)
        if cached_pdf is None:
            return None
        report_pdf_cache.move_to_end(cache_key)
        return cached_pdf

    def _cache_put(cache_key: tuple[object, ...], pdf: bytes) -> None:
        report_pdf_cache[cache_key] = pdf
        report_pdf_cache.move_to_end(cache_key)
        while len(report_pdf_cache) > _REPORT_PDF_CACHE_MAX_ENTRIES:
            evicted_key, _ = report_pdf_cache.popitem(last=False)
            report_pdf_locks.pop(evicted_key, None)
        # Prune stale locks that no longer have a cache entry or active holder
        if len(report_pdf_locks) > _REPORT_PDF_CACHE_MAX_ENTRIES * 2:
            stale_keys = [
                k
                for k, v in report_pdf_locks.items()
                if k not in report_pdf_cache and not v.locked()
            ]
            for k in stale_keys:
                report_pdf_locks.pop(k, None)

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

    def _require_run(run_id: str) -> dict[str, Any]:
        """Fetch a history run or raise 404."""
        run = state.history_db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    async def _async_require_run(run_id: str) -> dict[str, Any]:
        """Fetch a history run in a thread or raise 404."""
        run = await asyncio.to_thread(state.history_db.get_run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @router.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return {
            "status": "ok",
            "processing_state": state.processing_state,
            "processing_failures": state.processing_failure_count,
            "intake_stats": state.processor.intake_stats(),
        }

    # -- new settings endpoints (3-tab model) ----------------------------------

    @router.get("/api/settings/cars", response_model=CarsResponse)
    async def get_cars() -> CarsResponse:
        return state.settings_store.get_cars()

    @router.post("/api/settings/cars", response_model=CarsResponse)
    async def add_car(req: CarUpsertRequest) -> CarsResponse:
        payload = req.model_dump(exclude_none=True)
        result = await asyncio.to_thread(state.settings_store.add_car, payload)
        state.apply_car_settings()
        return result

    @router.put("/api/settings/cars/{car_id}", response_model=CarsResponse)
    async def update_car(car_id: str, req: CarUpsertRequest) -> CarsResponse:
        try:
            payload = req.model_dump(exclude_none=True)
            result = await asyncio.to_thread(
                state.settings_store.update_car,
                car_id,
                payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        state.apply_car_settings()
        return result

    @router.delete("/api/settings/cars/{car_id}", response_model=CarsResponse)
    async def delete_car(car_id: str) -> CarsResponse:
        try:
            result = await asyncio.to_thread(state.settings_store.delete_car, car_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state.apply_car_settings()
        return result

    @router.post("/api/settings/cars/active", response_model=CarsResponse)
    async def set_active_car(req: ActiveCarRequest) -> CarsResponse:
        car_id = req.carId
        try:
            result = await asyncio.to_thread(state.settings_store.set_active_car, car_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        state.apply_car_settings()
        return result

    @router.get("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def get_speed_source() -> SpeedSourceResponse:
        return state.settings_store.get_speed_source()

    @router.post("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def update_speed_source(req: SpeedSourceRequest) -> SpeedSourceResponse:
        payload = req.model_dump(exclude_none=True)
        result = await asyncio.to_thread(
            state.settings_store.update_speed_source,
            payload,
        )
        state.apply_speed_source_settings()
        return result

    @router.get("/api/settings/speed-source/status", response_model=SpeedSourceStatusResponse)
    async def get_speed_source_status() -> SpeedSourceStatusResponse:
        return state.gps_monitor.status_dict()

    def _sensors_response() -> SensorsResponse:
        return {"sensorsByMac": state.settings_store.get_sensors()}

    @router.get("/api/settings/sensors", response_model=SensorsResponse)
    async def get_sensors() -> SensorsResponse:
        return _sensors_response()

    @router.post("/api/settings/sensors/{mac}", response_model=SensorsResponse)
    async def update_sensor(mac: str, req: SensorRequest) -> SensorsResponse:
        try:
            payload = req.model_dump(exclude_none=True)
            await asyncio.to_thread(
                state.settings_store.set_sensor,
                mac,
                payload,
            )
            return _sensors_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/settings/sensors/{mac}", response_model=SensorsResponse)
    async def delete_sensor(mac: str) -> SensorsResponse:
        try:
            removed = await asyncio.to_thread(state.settings_store.remove_sensor, mac)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown sensor MAC")
        return _sensors_response()

    @router.get("/api/settings/language", response_model=LanguageResponse)
    async def get_language() -> LanguageResponse:
        return {"language": state.settings_store.language}

    @router.post("/api/settings/language", response_model=LanguageResponse)
    async def set_language(req: LanguageRequest) -> LanguageResponse:
        try:
            language = await asyncio.to_thread(state.settings_store.set_language, req.language)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"language": language}

    @router.get("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def get_speed_unit() -> SpeedUnitResponse:
        return {"speedUnit": state.settings_store.speed_unit}

    @router.post("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def set_speed_unit(req: SpeedUnitRequest) -> SpeedUnitResponse:
        try:
            unit = await asyncio.to_thread(state.settings_store.set_speed_unit, req.speedUnit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"speedUnit": unit}

    # -- client & location endpoints -------------------------------------------

    @router.get("/api/clients", response_model=ClientsResponse)
    async def get_clients() -> ClientsResponse:
        return {"clients": state.registry.snapshot_for_api()}

    @router.get("/api/client-locations", response_model=ClientLocationsResponse)
    async def get_client_locations() -> ClientLocationsResponse:
        return {"locations": all_locations()}

    @router.post("/api/simulator/speed-override", response_model=SpeedSourceResponse)
    async def set_simulator_speed_override(req: SpeedSourceRequest) -> SpeedSourceResponse:
        return await update_speed_source(req)

    @router.get("/api/analysis-settings", response_model=AnalysisSettingsResponse)
    async def get_analysis_settings() -> AnalysisSettingsResponse:
        return state.analysis_settings.snapshot()

    @router.post("/api/analysis-settings", response_model=AnalysisSettingsResponse)
    async def set_analysis_settings(req: AnalysisSettingsRequest) -> AnalysisSettingsResponse:
        changes = req.model_dump(exclude_none=True)
        if changes:
            try:
                await asyncio.to_thread(state.settings_store.update_active_car_aspects, changes)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            state.apply_car_settings()
        return state.analysis_settings.snapshot()

    @router.post("/api/clients/{client_id}/identify", response_model=IdentifyResponse)
    async def identify_client(client_id: str, req: IdentifyRequest) -> IdentifyResponse:
        normalized = _normalize_client_id_or_400(client_id)
        ok, cmd_seq = state.control_plane.send_identify(normalized, req.duration_ms)
        if not ok:
            raise HTTPException(status_code=404, detail="Client missing or no control address")
        return {"status": "sent", "cmd_seq": cmd_seq}

    @router.post(
        "/api/clients/{client_id}/location",
        response_model=SetClientLocationResponse,
    )
    async def set_client_location(
        client_id: str,
        req: SetLocationRequest,
    ) -> SetClientLocationResponse:
        normalized_client_id = _normalize_client_id_or_400(client_id)
        if state.registry.get(normalized_client_id) is None:
            raise HTTPException(status_code=404, detail="Unknown client_id")

        code = req.location_code.strip()

        if code:
            label = label_for_code(code)
            if label is None:
                raise HTTPException(status_code=400, detail="Unknown location_code")

            for row in state.registry.snapshot_for_api():
                if row["id"] != normalized_client_id and row.get("location") == code:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Location already assigned to client {row['id']}",
                    )

            updated = state.registry.set_name(normalized_client_id, label)
        else:
            # Empty location_code → clear the assignment
            updated = state.registry.clear_name(normalized_client_id)

        state.registry.set_location(normalized_client_id, code)
        mac = client_id_mac(updated.client_id)
        await asyncio.to_thread(state.settings_store.set_sensor, mac, {"location": code})
        return {
            "id": updated.client_id,
            "mac_address": mac,
            "location_code": code,
            "name": updated.name,
        }

    @router.delete("/api/clients/{client_id}", response_model=RemoveClientResponse)
    async def remove_client(client_id: str) -> RemoveClientResponse:
        normalized_client_id = _normalize_client_id_or_400(client_id)
        removed = state.registry.remove_client(normalized_client_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown client_id")
        return {"id": normalized_client_id, "status": "removed"}

    @router.get("/api/logging/status", response_model=LoggingStatusResponse)
    async def get_logging_status() -> LoggingStatusResponse:
        return state.metrics_logger.status()

    @router.post("/api/logging/start", response_model=LoggingStatusResponse)
    async def start_logging() -> LoggingStatusResponse:
        state.live_diagnostics.reset()
        return state.metrics_logger.start_logging()

    @router.post("/api/logging/stop", response_model=LoggingStatusResponse)
    async def stop_logging() -> LoggingStatusResponse:
        return state.metrics_logger.stop_logging()

    @router.get("/api/history", response_model=HistoryListResponse)
    async def get_history() -> HistoryListResponse:
        runs = await asyncio.to_thread(state.history_db.list_runs)
        return {"runs": runs}

    @router.get("/api/history/{run_id}", response_model=HistoryRunResponse)
    async def get_history_run(run_id: str) -> HistoryRunResponse:
        return await _async_require_run(run_id)

    @router.get("/api/history/{run_id}/insights", response_model=HistoryInsightsResponse)
    async def get_history_insights(
        run_id: str,
        lang: str | None = Query(default=None),
    ) -> HistoryInsightsResponse:
        run = await _async_require_run(run_id)
        if run["status"] == "analyzing":
            return {"run_id": run_id, "status": "analyzing"}
        if run["status"] == "error":
            raise HTTPException(status_code=422, detail=run.get("error_message", "Analysis failed"))
        analysis = run.get("analysis")
        if analysis is None:
            raise HTTPException(status_code=422, detail="No analysis available for this run")

        # Expose staleness to callers so they can decide whether to re-request
        analysis_version = run.get("analysis_version")
        if isinstance(analysis, dict) and analysis_version is not None:
            from .history_db import ANALYSIS_SCHEMA_VERSION

            try:
                analysis["_analysis_is_current"] = int(analysis_version) >= ANALYSIS_SCHEMA_VERSION
            except (TypeError, ValueError):
                analysis["_analysis_is_current"] = False

        # Re-run analysis only when a *different* language is explicitly
        # requested.  The post-stop pipeline is the single source of truth;
        # on-demand re-computation is reserved for language variants only.
        from .report_i18n import normalize_lang as _norm_lang

        requested_lang = _norm_lang(lang) if lang is not None else None
        persisted_lang = _norm_lang(analysis.get("lang")) if isinstance(analysis, dict) else None
        if requested_lang is not None and requested_lang != persisted_lang:

            def _recompute() -> dict:
                samples, total_samples, stride = _bounded_sample(
                    _iter_normalized_samples(run_id),
                    max_items=_MAX_REPORT_SAMPLES,
                )
                metadata = run.get("metadata", {})
                result = summarize_run_data(
                    metadata,
                    samples,
                    lang=requested_lang,
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

        # Strip internal renderer-only fields before returning
        if isinstance(analysis, dict):
            analysis = {k: v for k, v in analysis.items() if not k.startswith("_")}
        return analysis

    @router.delete("/api/history/{run_id}", response_model=DeleteHistoryRunResponse)
    async def delete_history_run(run_id: str) -> DeleteHistoryRunResponse:
        deleted, reason = await asyncio.to_thread(state.history_db.delete_run_if_safe, run_id)
        if not deleted:
            if reason == "not_found":
                raise HTTPException(status_code=404, detail="Run not found")
            if reason == "active":
                raise HTTPException(
                    status_code=409,
                    detail="Cannot delete the active run; stop recording first",
                )
            if reason == "analyzing":
                raise HTTPException(
                    status_code=409,
                    detail="Cannot delete run while analysis is in progress",
                )
            raise HTTPException(status_code=409, detail=f"Cannot delete run: {reason}")
        return {"run_id": run_id, "status": "deleted"}

    @router.get("/api/history/{run_id}/report.pdf")
    async def download_history_report_pdf(
        run_id: str, lang: str | None = Query(default=None)
    ) -> Response:
        run = await _async_require_run(run_id)
        analysis = run.get("analysis")
        if analysis is None:
            raise HTTPException(status_code=422, detail="No analysis available for this run")
        requested_lang = _analysis_language(run, lang)
        cache_key = _report_pdf_cache_key(run, run_id, requested_lang)
        pdf_name = f"{_safe_filename(run_id)}_report.pdf"
        pdf_headers = {
            "Content-Disposition": f'attachment; filename="{pdf_name}"',
        }
        cached_pdf = _cache_get(cache_key)
        if cached_pdf is not None:
            return Response(
                content=cached_pdf,
                media_type="application/pdf",
                headers=pdf_headers,
            )

        def _build_pdf() -> bytes:
            # Prefer pre-built ReportTemplateData from analysis when the
            # language matches.  If the caller requested a different language,
            # fall through to rebuild via map_summary().
            report_data_dict = (
                analysis.get("_report_template_data") if isinstance(analysis, dict) else None
            )
            if isinstance(report_data_dict, dict):
                persisted_lang = str(report_data_dict.get("lang") or "en").strip().lower()
                if persisted_lang == requested_lang:
                    data = _reconstruct_report_template_data(report_data_dict)
                    return build_report_pdf(data)

            # Rebuild from persisted summary (language mismatch or data
            # without _report_template_data).
            from .analysis import map_summary

            summary = dict(analysis) if isinstance(analysis, dict) else {}
            summary["lang"] = requested_lang
            data = map_summary(summary)
            return build_report_pdf(data)

        build_lock = report_pdf_locks.setdefault(cache_key, asyncio.Lock())
        async with build_lock:
            cached_pdf = _cache_get(cache_key)
            if cached_pdf is not None:
                return Response(
                    content=cached_pdf,
                    media_type="application/pdf",
                    headers=pdf_headers,
                )
            pdf = await asyncio.to_thread(_build_pdf)
            _cache_put(cache_key, pdf)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers=pdf_headers,
        )

    @router.get("/api/history/{run_id}/export")
    async def export_history_run(run_id: str) -> Response:
        run = await _async_require_run(run_id)

        def _build_zip() -> bytes:
            safe_name = _safe_filename(run_id)
            fieldnames: list[str] = []
            fieldname_set: set[str] = set()
            sample_count = 0

            # Wrap both read passes in a single read transaction so the
            # data cannot change between the fieldname scan and CSV write.
            from contextlib import nullcontext

            read_tx = getattr(state.history_db, "read_transaction", None)
            tx_ctx = read_tx() if callable(read_tx) else nullcontext()
            with tx_ctx:
                for batch in state.history_db.iter_run_samples(
                    run_id, batch_size=_EXPORT_BATCH_SIZE
                ):
                    sample_count += len(batch)
                    for sample in batch:
                        for key in sample:
                            if key not in fieldname_set:
                                fieldname_set.add(key)
                                fieldnames.append(key)

                run_details = dict(run)
                run_details["sample_count"] = sample_count

                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(
                    zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    archive.writestr(
                        f"{safe_name}.json",
                        json.dumps(run_details, ensure_ascii=False, indent=2, sort_keys=True),
                    )
                    if fieldnames:
                        with archive.open(f"{safe_name}_raw.csv", mode="w") as raw_csv:
                            raw_csv_text = io.TextIOWrapper(raw_csv, encoding="utf-8", newline="")
                            writer = csv.DictWriter(
                                raw_csv_text,
                                fieldnames=fieldnames,
                                extrasaction="ignore",
                            )
                            writer.writeheader()
                            for batch in state.history_db.iter_run_samples(
                                run_id, batch_size=_EXPORT_BATCH_SIZE
                            ):
                                writer.writerows([_flatten_for_csv(row) for row in batch])
                            raw_csv_text.flush()
                    else:
                        archive.writestr(f"{safe_name}_raw.csv", "")
            return zip_buffer.getvalue()

        content = await asyncio.to_thread(_build_zip)
        safe_name = _safe_filename(run_id)
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
            },
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

    @router.get("/api/car-library/brands", response_model=CarLibraryBrandsResponse)
    async def get_car_library_brands() -> CarLibraryBrandsResponse:
        from .car_library import get_brands

        return {"brands": get_brands()}

    @router.get("/api/car-library/types", response_model=CarLibraryTypesResponse)
    async def get_car_library_types(brand: str = Query(...)) -> CarLibraryTypesResponse:
        from .car_library import get_types_for_brand

        return {"types": get_types_for_brand(brand)}

    @router.get("/api/car-library/models", response_model=CarLibraryModelsResponse)
    async def get_car_library_models(
        brand: str = Query(...), car_type: str = Query(..., alias="type")
    ) -> CarLibraryModelsResponse:
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
