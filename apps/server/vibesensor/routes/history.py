"""History CRUD, insights, PDF report download, and CSV/ZIP export endpoints."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import tempfile
import zipfile
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from ..api_models import (
    DeleteHistoryRunResponse,
    HistoryInsightsResponse,
    HistoryListResponse,
    HistoryRunResponse,
)
from ..report.pdf_builder import build_report_pdf
from ._helpers import async_require_run, safe_filename

if TYPE_CHECKING:
    from ..app import RuntimeState
    from ..report.report_data import ReportTemplateData

LOGGER = logging.getLogger(__name__)

_EXPORT_BATCH_SIZE = 2048
_EXPORT_SPOOL_THRESHOLD = 4 * 1024 * 1024  # 4 MB before spilling to disk
_EXPORT_STREAM_CHUNK = 1024 * 1024  # 1 MB read chunks when streaming
_REPORT_PDF_CACHE_MAX_ENTRIES = 16

# Fixed CSV column order derived from SensorFrame canonical keys.
# Using a fixed schema avoids a pre-scan pass to discover columns.
# Any sample keys not in this list are serialized into the ``extras`` column.
EXPORT_CSV_COLUMNS: tuple[str, ...] = (
    "record_type",
    "schema_version",
    "run_id",
    "timestamp_utc",
    "t_s",
    "client_id",
    "client_name",
    "location",
    "sample_rate_hz",
    "speed_kmh",
    "gps_speed_kmh",
    "speed_source",
    "engine_rpm",
    "engine_rpm_source",
    "gear",
    "final_drive_ratio",
    "accel_x_g",
    "accel_y_g",
    "accel_z_g",
    "dominant_freq_hz",
    "dominant_axis",
    "top_peaks",
    "top_peaks_x",
    "top_peaks_y",
    "top_peaks_z",
    "vibration_strength_db",
    "strength_bucket",
    "strength_peak_amp_g",
    "strength_floor_amp_g",
    "frames_dropped_total",
    "queue_overflow_drops",
    "extras",
)

_EXPORT_CSV_COLUMN_SET: frozenset[str] = frozenset(EXPORT_CSV_COLUMNS) - {"extras"}


def flatten_for_csv(row: dict[str, Any]) -> dict[str, Any]:
    """Convert nested/complex values to JSON strings for CSV export.

    ``csv.DictWriter`` calls ``str()`` on values, which produces Python
    repr for dicts/lists (single-quoted keys, etc.).  Serializing them as
    JSON ensures the output is parseable by non-Python consumers.

    Keys not in the fixed CSV column set are collected into an ``extras``
    column as a JSON object.
    """
    out: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    for k, v in row.items():
        if k in _EXPORT_CSV_COLUMN_SET:
            out[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        else:
            extras[k] = v
    # Ensure record_type and schema_version are always populated.
    out.setdefault("record_type", "sample")
    out.setdefault("schema_version", "2")
    if extras:
        out["extras"] = json.dumps(extras, ensure_ascii=False)
    return out


def _reconstruct_report_template_data(d: dict) -> ReportTemplateData:
    """Reconstruct a :class:`ReportTemplateData` from a persisted dict."""
    from ..report.report_data import ReportTemplateData

    return ReportTemplateData.from_dict(d)


def create_history_routes(state: RuntimeState) -> APIRouter:
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

    def _report_pdf_cache_lang(run: dict[str, Any], requested_lang: str) -> str:
        analysis = run.get("analysis")
        if isinstance(analysis, dict):
            report_data_dict = analysis.get("_report_template_data")
            if isinstance(report_data_dict, dict):
                persisted_lang = str(report_data_dict.get("lang") or "").strip().lower()
                if persisted_lang:
                    return persisted_lang
        return requested_lang

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
        _prune_stale_pdf_locks()

    def _prune_stale_pdf_locks() -> None:
        """Remove locks that have no cache entry and are not currently held."""
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

    # -- history CRUD ----------------------------------------------------------

    @router.get("/api/history", response_model=HistoryListResponse)
    async def get_history() -> HistoryListResponse:
        runs = await asyncio.to_thread(state.history_db.list_runs)
        return {"runs": runs}

    @router.get("/api/history/{run_id}", response_model=HistoryRunResponse)
    async def get_history_run(run_id: str) -> HistoryRunResponse:
        return await async_require_run(state.history_db, run_id)

    @router.get("/api/history/{run_id}/insights", response_model=HistoryInsightsResponse)
    async def get_history_insights(
        run_id: str,
        lang: str | None = Query(default=None),
    ) -> HistoryInsightsResponse:
        run = await async_require_run(state.history_db, run_id)
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
            from ..history_db import ANALYSIS_SCHEMA_VERSION

            try:
                analysis["analysis_is_current"] = int(analysis_version) >= ANALYSIS_SCHEMA_VERSION
            except (TypeError, ValueError):
                analysis["analysis_is_current"] = False

        # Keep /insights read-only: return persisted post-stop analysis as-is.
        # The optional lang query is accepted for compatibility but does not
        # trigger on-demand analysis recomputation.
        _ = lang

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
            raise HTTPException(status_code=409, detail="Cannot delete run at this time")
        return {"run_id": run_id, "status": "deleted"}

    # -- report PDF ------------------------------------------------------------

    @router.get("/api/history/{run_id}/report.pdf")
    async def download_history_report_pdf(
        run_id: str, lang: str | None = Query(default=None)
    ) -> Response:
        run = await async_require_run(state.history_db, run_id)
        if run.get("status") == "analyzing":
            raise HTTPException(status_code=409, detail="Analysis is still in progress")
        if run.get("status") == "error":
            raise HTTPException(
                status_code=422,
                detail=run.get("error_message", "Analysis failed"),
            )
        analysis = run.get("analysis")
        if analysis is None:
            raise HTTPException(status_code=422, detail="No analysis available for this run")
        requested_lang = _analysis_language(run, lang)
        cache_key = _report_pdf_cache_key(run, run_id, _report_pdf_cache_lang(run, requested_lang))
        pdf_name = f"{safe_filename(run_id)}_report.pdf"
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
            # Prefer pre-built ReportTemplateData from post-stop analysis.
            # Keep report generation rendering-only: do not re-run analysis
            # mapping when persisted template data is available.
            report_data_dict = (
                analysis.get("_report_template_data") if isinstance(analysis, dict) else None
            )
            if isinstance(report_data_dict, dict):
                data = _reconstruct_report_template_data(report_data_dict)
                return build_report_pdf(data)

            # Rebuild from persisted summary only for legacy runs without
            # persisted _report_template_data.
            from ..analysis import map_summary

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
            try:
                pdf = await asyncio.to_thread(_build_pdf)
            except Exception as exc:
                LOGGER.warning("PDF generation failed for run %s", run_id, exc_info=True)
                # Prune stale locks even on failure to prevent unbounded growth
                _prune_stale_pdf_locks()
                raise HTTPException(
                    status_code=422,
                    detail="PDF generation failed. Please try again or re-analyze this run.",
                ) from exc
            _cache_put(cache_key, pdf)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers=pdf_headers,
        )

    # -- CSV/ZIP export --------------------------------------------------------

    @router.get("/api/history/{run_id}/export")
    async def export_history_run(run_id: str) -> StreamingResponse:
        run = await async_require_run(state.history_db, run_id)

        def _build_zip_file() -> tempfile.SpooledTemporaryFile[bytes]:
            """Build the export ZIP into a spooled temp file (single-pass)."""
            safe_name = safe_filename(run_id)
            sample_count = 0

            spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
                max_size=_EXPORT_SPOOL_THRESHOLD
            )
            try:
                with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                    # Write CSV with fixed column schema (single pass).
                    with archive.open(f"{safe_name}_raw.csv", mode="w") as raw_csv:
                        raw_csv_text = io.TextIOWrapper(raw_csv, encoding="utf-8", newline="")
                        writer = csv.DictWriter(
                            raw_csv_text,
                            fieldnames=EXPORT_CSV_COLUMNS,
                            extrasaction="ignore",
                        )
                        writer.writeheader()
                        for batch in state.history_db.iter_run_samples(
                            run_id, batch_size=_EXPORT_BATCH_SIZE
                        ):
                            sample_count += len(batch)
                            writer.writerows([flatten_for_csv(row) for row in batch])
                        raw_csv_text.flush()

                    # Write run metadata as JSON (after CSV so sample_count is known).
                    # Strip internal-only fields (prefixed with _) from analysis
                    # to avoid leaking implementation details into exported data.
                    run_details = dict(run)
                    run_details["sample_count"] = sample_count
                    analysis = run_details.get("analysis")
                    if isinstance(analysis, dict):
                        run_details["analysis"] = {
                            k: v for k, v in analysis.items() if not k.startswith("_")
                        }
                    try:
                        details_json = json.dumps(
                            run_details,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                            allow_nan=False,
                        )
                    except ValueError:
                        # Analysis data may contain NaN/Inf floats;
                        # fall back so the export still succeeds.
                        LOGGER.warning("Export run %s: analysis contains non-finite floats", run_id)
                        details_json = json.dumps(
                            run_details,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                            allow_nan=True,
                        )
                    archive.writestr(f"{safe_name}.json", details_json)

                spool.seek(0)
            except BaseException:
                spool.close()
                raise
            return spool

        spool = await asyncio.to_thread(_build_zip_file)
        file_size = spool.seek(0, 2)
        spool.seek(0)

        def _iter_spool():
            try:
                while True:
                    chunk = spool.read(_EXPORT_STREAM_CHUNK)
                    if not chunk:
                        break
                    yield chunk
            finally:
                spool.close()

        safe_name = safe_filename(run_id)
        return StreamingResponse(
            content=_iter_spool(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
                "Content-Length": str(file_size),
            },
        )

    return router
