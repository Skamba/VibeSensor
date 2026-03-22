"""Persisted history-report loading and request shaping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from vibesensor.domain import CarSnapshot
from vibesensor.shared.boundaries.summary_warning import summary_warning_payloads
from vibesensor.shared.exceptions import AnalysisNotReadyError
from vibesensor.shared.ports import RunPersistence, SettingsReader
from vibesensor.shared.run_context import add_current_context_warnings, current_car_snapshot_token
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object
from vibesensor.use_cases.history.helpers import (
    HistoryRecord,
    async_require_run,
    require_analysis_ready,
    resolve_run_language,
    safe_filename,
)
from vibesensor.use_cases.history.report_cache import ReportPdfCacheKey

if TYPE_CHECKING:
    from vibesensor.domain import TestRun


@dataclass(frozen=True)
class HistoryReportRequest:
    """Resolved persisted report context ready for PDF generation."""

    cache_key: ReportPdfCacheKey
    filename: str
    analysis_summary: JsonObject
    domain_test_run: TestRun | None = None


class HistoryReportRequestLoader:
    """Load persisted report data and shape it for PDF generation."""

    __slots__ = ("_history_db", "_settings_store")

    def __init__(
        self,
        history_db: RunPersistence,
        settings_store: SettingsReader | None = None,
    ) -> None:
        self._history_db = history_db
        self._settings_store = settings_store

    async def load_report_request(
        self,
        run_id: str,
        requested_lang: str | None,
    ) -> HistoryReportRequest:
        run = await async_require_run(self._history_db, run_id)
        analysis = require_analysis_ready(run)
        if not isinstance(analysis, dict) or not isinstance(analysis.get("findings"), list):
            raise AnalysisNotReadyError(
                "Report data unavailable for this run. Re-analyze to regenerate the PDF."
            )

        requested_lang = self._analysis_language(run, requested_lang)
        current_active_car_snapshot = (
            self._settings_store.active_car_snapshot() if self._settings_store is not None else None
        )
        warnings = add_current_context_warnings(
            analysis.get("warnings"),
            metadata=analysis.get("metadata"),
            current_active_car_snapshot=current_active_car_snapshot,
        )
        analysis_summary = dict(analysis)
        analysis_summary["warnings"] = cast(JsonValue, summary_warning_payloads(warnings))
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
    def _metadata_cache_token(metadata: object) -> str:
        if not is_json_object(metadata):
            return "{}"
        return json.dumps(metadata, sort_keys=True, default=str, ensure_ascii=False)

    def _report_pdf_cache_key(
        self,
        run: HistoryRecord,
        run_id: str,
        requested_lang: str,
        *,
        current_active_car_snapshot: CarSnapshot | None,
    ) -> ReportPdfCacheKey:
        return (
            run_id,
            requested_lang,
            str(run["analysis_completed_at"]) if "analysis_completed_at" in run else None,
            int(run.get("sample_count", 0)),
            self._metadata_cache_token(run.get("metadata", {})),
            current_car_snapshot_token(current_active_car_snapshot),
        )

    @staticmethod
    def _report_pdf_cache_lang(run: HistoryRecord, requested_lang: str) -> str:
        analysis = run.get("analysis")
        if is_json_object(analysis):
            persisted_lang = str(analysis.get("lang") or "").strip().lower()
            if persisted_lang:
                return persisted_lang
        return requested_lang

    @staticmethod
    def _analysis_language(run: HistoryRecord, requested: str | None) -> str:
        return resolve_run_language(run, requested)
