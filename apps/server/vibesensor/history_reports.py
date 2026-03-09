"""PDF report loading, language resolution, cache, and coordination."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, cast

from fastapi import HTTPException

from .analysis import map_summary
from .backend_types import CarConfigPayload, HistoryRunPayload
from .history_helpers import async_require_run, require_analysis_ready, safe_filename
from .json_types import JsonObject, is_json_object
from .report.pdf_engine import build_report_pdf
from .run_context import add_current_context_warnings, current_car_snapshot_token

if TYPE_CHECKING:
    from .history_db import HistoryDB
    from .settings_store import SettingsStore

LOGGER = logging.getLogger(__name__)

REPORT_PDF_CACHE_MAX_ENTRIES = 16
ReportPdfCacheKey = tuple[str, str, int | None, str | None, int, str, str]


@dataclass(frozen=True)
class HistoryReportPdf:
    """Ready-to-send PDF download payload."""

    content: bytes
    filename: str


@dataclass(frozen=True)
class HistoryReportRequest:
    """Resolved persisted report context ready for PDF generation."""

    cache_key: ReportPdfCacheKey
    filename: str
    analysis_summary: JsonObject


class HistoryReportService:
    """Load persisted report data and coordinate cached PDF generation."""

    __slots__ = ("_history_db", "_pdf_cache", "_settings_store")

    def __init__(self, history_db: HistoryDB, settings_store: SettingsStore | None = None) -> None:
        self._history_db = history_db
        self._pdf_cache = HistoryReportPdfCache()
        self._settings_store = settings_store

    async def build_pdf(self, run_id: str, requested_lang: str | None) -> HistoryReportPdf:
        request = await self.load_report_request(run_id, requested_lang)
        cached_pdf = self._pdf_cache.get(request.cache_key)
        if cached_pdf is not None:
            return HistoryReportPdf(content=cached_pdf, filename=request.filename)

        pdf = await self._pdf_cache.get_or_build(
            request.cache_key,
            lambda: self._build_pdf_bytes(request.analysis_summary),
            run_id=run_id,
        )
        return HistoryReportPdf(content=pdf, filename=request.filename)

    async def load_report_request(
        self,
        run_id: str,
        requested_lang: str | None,
    ) -> HistoryReportRequest:
        run = await async_require_run(self._history_db, run_id)
        analysis = require_analysis_ready(run)
        if not isinstance(analysis, dict) or not isinstance(analysis.get("findings"), list):
            raise HTTPException(
                status_code=422,
                detail="Report data unavailable for this run. Re-analyze to regenerate the PDF.",
            )

        requested_lang = self._analysis_language(run, requested_lang)
        active_car_snapshot = (
            getattr(self._settings_store, "active_car_snapshot", None)
            if self._settings_store is not None
            else None
        )
        current_active_car_snapshot = (
            active_car_snapshot() if callable(active_car_snapshot) else None
        )
        analysis_summary = add_current_context_warnings(
            analysis,
            current_active_car_snapshot=current_active_car_snapshot,
        )
        cache_key = self._report_pdf_cache_key(
            run,
            run_id,
            self._report_pdf_cache_lang(run, requested_lang),
            current_active_car_snapshot=current_active_car_snapshot,
        )
        return HistoryReportRequest(
            cache_key=cache_key,
            filename=f"{safe_filename(run_id)}_report.pdf",
            analysis_summary=analysis_summary,
        )

    @staticmethod
    def _build_pdf_bytes(analysis_summary: JsonObject) -> bytes:
        return cast(bytes, build_report_pdf(map_summary(analysis_summary)))

    @staticmethod
    def _metadata_cache_token(metadata: object) -> str:
        if not is_json_object(metadata):
            return "{}"
        return json.dumps(metadata, sort_keys=True, default=str, ensure_ascii=False)

    def _report_pdf_cache_key(
        self,
        run: HistoryRunPayload,
        run_id: str,
        requested_lang: str,
        *,
        current_active_car_snapshot: CarConfigPayload | None,
    ) -> ReportPdfCacheKey:
        return (
            run_id,
            requested_lang,
            int(run["analysis_version"]) if "analysis_version" in run else None,
            str(run["analysis_completed_at"]) if "analysis_completed_at" in run else None,
            int(run.get("sample_count", 0)),
            self._metadata_cache_token(run.get("metadata", {})),
            current_car_snapshot_token(current_active_car_snapshot),
        )

    @staticmethod
    def _report_pdf_cache_lang(run: HistoryRunPayload, requested_lang: str) -> str:
        analysis = run.get("analysis")
        if is_json_object(analysis):
            persisted_lang = str(analysis.get("lang") or "").strip().lower()
            if persisted_lang:
                return persisted_lang
        return requested_lang

    @staticmethod
    def _analysis_language(run: HistoryRunPayload, requested: str | None) -> str:
        if isinstance(requested, str) and requested.strip():
            return requested.strip().lower()
        metadata: object = run.get("metadata", {})
        if is_json_object(metadata):
            value = metadata.get("language")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return "en"


class HistoryReportPdfCache:
    """LRU PDF cache plus per-key build coordination."""

    __slots__ = ("_entries", "_locks")

    def __init__(self) -> None:
        self._entries: OrderedDict[ReportPdfCacheKey, bytes] = OrderedDict()
        self._locks: dict[ReportPdfCacheKey, asyncio.Lock] = {}

    def get(self, cache_key: ReportPdfCacheKey) -> bytes | None:
        cached_pdf = self._entries.get(cache_key)
        if cached_pdf is None:
            return None
        self._entries.move_to_end(cache_key)
        return cached_pdf

    async def get_or_build(
        self,
        cache_key: ReportPdfCacheKey,
        build_pdf: Callable[[], bytes],
        *,
        run_id: str,
    ) -> bytes:
        build_lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with build_lock:
            cached_pdf = self.get(cache_key)
            if cached_pdf is not None:
                return cached_pdf
            try:
                pdf = await asyncio.to_thread(build_pdf)
            except Exception as exc:
                LOGGER.warning("PDF generation failed for run %s", run_id, exc_info=True)
                self._prune_stale_locks()
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "PDF generation failed due to an internal error."
                        " Please try again or re-analyze this run."
                    ),
                ) from exc
            self._put(cache_key, pdf)
            return pdf

    def _put(self, cache_key: ReportPdfCacheKey, pdf: bytes) -> None:
        self._entries[cache_key] = pdf
        self._entries.move_to_end(cache_key)
        while len(self._entries) > REPORT_PDF_CACHE_MAX_ENTRIES:
            evicted_key, _ = self._entries.popitem(last=False)
            self._locks.pop(evicted_key, None)
        self._prune_stale_locks()

    def _prune_stale_locks(self) -> None:
        if len(self._locks) > REPORT_PDF_CACHE_MAX_ENTRIES * 2:
            stale_keys = [
                key
                for key, lock in self._locks.items()
                if key not in self._entries and not lock.locked()
            ]
            for key in stale_keys:
                self._locks.pop(key, None)
