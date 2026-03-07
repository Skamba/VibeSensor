"""PDF report loading, language resolution, cache, and coordination."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from .history_helpers import async_require_run, require_analysis_ready, safe_filename
from .report.pdf_builder import build_report_pdf

if TYPE_CHECKING:
    from .history_db import HistoryDB
    from .report.report_data import ReportTemplateData

LOGGER = logging.getLogger(__name__)

REPORT_PDF_CACHE_MAX_ENTRIES = 16


@dataclass(frozen=True)
class HistoryReportPdf:
    """Ready-to-send PDF download payload."""

    content: bytes
    filename: str


@dataclass(frozen=True)
class HistoryReportRequest:
    """Resolved persisted report context ready for PDF generation."""

    cache_key: tuple[object, ...]
    filename: str
    report_data_dict: dict[str, Any]


def reconstruct_report_template_data(data: dict[str, Any]) -> ReportTemplateData:
    """Reconstruct a ReportTemplateData object from a persisted dict."""
    from .report.report_data import ReportTemplateData

    return ReportTemplateData.from_dict(data)


class HistoryReportService:
    """Load persisted report data and coordinate cached PDF generation."""

    __slots__ = ("_history_db", "_pdf_cache")

    def __init__(self, history_db: HistoryDB) -> None:
        self._history_db = history_db
        self._pdf_cache = HistoryReportPdfCache()

    async def build_pdf(self, run_id: str, requested_lang: str | None) -> HistoryReportPdf:
        request = await self.load_report_request(run_id, requested_lang)
        cached_pdf = self._pdf_cache.get(request.cache_key)
        if cached_pdf is not None:
            return HistoryReportPdf(content=cached_pdf, filename=request.filename)

        pdf = await self._pdf_cache.get_or_build(
            request.cache_key,
            lambda: self._build_pdf_bytes(request.report_data_dict),
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
        report_data_dict = (
            analysis.get("_report_template_data") if isinstance(analysis, dict) else None
        )
        if not isinstance(report_data_dict, dict):
            raise HTTPException(
                status_code=422,
                detail="Report data unavailable for this run. Re-analyze to regenerate the PDF.",
            )

        requested_lang = self._analysis_language(run, requested_lang)
        cache_key = self._report_pdf_cache_key(
            run,
            run_id,
            self._report_pdf_cache_lang(run, requested_lang),
        )
        return HistoryReportRequest(
            cache_key=cache_key,
            filename=f"{safe_filename(run_id)}_report.pdf",
            report_data_dict=report_data_dict,
        )

    @staticmethod
    def _build_pdf_bytes(report_data_dict: dict[str, Any]) -> bytes:
        data = reconstruct_report_template_data(report_data_dict)
        return build_report_pdf(data)

    @staticmethod
    def _metadata_cache_token(metadata: object) -> str:
        if not isinstance(metadata, dict):
            return "{}"
        return json.dumps(metadata, sort_keys=True, default=str, ensure_ascii=False)

    def _report_pdf_cache_key(
        self,
        run: dict[str, Any],
        run_id: str,
        requested_lang: str,
    ) -> tuple[object, ...]:
        return (
            run_id,
            requested_lang,
            run.get("analysis_version"),
            run.get("analysis_completed_at"),
            run.get("sample_count"),
            self._metadata_cache_token(run.get("metadata", {})),
        )

    @staticmethod
    def _report_pdf_cache_lang(run: dict[str, Any], requested_lang: str) -> str:
        analysis = run.get("analysis")
        if isinstance(analysis, dict):
            report_data_dict = analysis.get("_report_template_data")
            if isinstance(report_data_dict, dict):
                persisted_lang = str(report_data_dict.get("lang") or "").strip().lower()
                if persisted_lang:
                    return persisted_lang
        return requested_lang

    @staticmethod
    def _analysis_language(run: dict[str, Any], requested: str | None) -> str:
        if isinstance(requested, str) and requested.strip():
            return requested.strip().lower()
        metadata = run.get("metadata", {})
        if isinstance(metadata, dict):
            value = metadata.get("language")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return "en"


class HistoryReportPdfCache:
    """LRU PDF cache plus per-key build coordination."""

    __slots__ = ("_entries", "_locks")

    def __init__(self) -> None:
        self._entries: OrderedDict[tuple[object, ...], bytes] = OrderedDict()
        self._locks: dict[tuple[object, ...], asyncio.Lock] = {}

    def get(self, cache_key: tuple[object, ...]) -> bytes | None:
        cached_pdf = self._entries.get(cache_key)
        if cached_pdf is None:
            return None
        self._entries.move_to_end(cache_key)
        return cached_pdf

    async def get_or_build(
        self,
        cache_key: tuple[object, ...],
        build_pdf,
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

    def _put(self, cache_key: tuple[object, ...], pdf: bytes) -> None:
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
