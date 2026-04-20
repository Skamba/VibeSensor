"""Persisted history-report loading and canonical prepared-report handoff."""

from __future__ import annotations

import json
from dataclasses import dataclass

from vibesensor.domain import RunStatus
from vibesensor.shared.boundaries.reporting import (
    PreparedReportInput,
    prepare_persisted_report_input,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_to_json_object
from vibesensor.shared.exceptions import AnalysisNotReadyError
from vibesensor.shared.filenames import safe_filename
from vibesensor.shared.ports import AsyncRunPersistence
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.json_types import is_json_array
from vibesensor.shared.types.report_cache import ReportPdfCacheKey
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.history.helpers import (
    async_require_run,
    resolve_run_language,
)

_PERSISTED_REPORT_MODE_TOKEN = "none"


@dataclass(frozen=True)
class HistoryReportRequest:
    """Resolved persisted report request with a canonical prepared report input."""

    prepared: PreparedReportInput

    @property
    def cache_key(self) -> ReportPdfCacheKey:
        cache_key = self.prepared.cache_key
        if cache_key is None:
            raise RuntimeError("Persisted history report requests must carry a cache key")
        return cache_key

    @property
    def filename(self) -> str:
        return self.prepared.filename


class HistoryReportRequestLoader:
    """Load persisted report data and prepare the canonical report input."""

    __slots__ = ("_history_db",)

    def __init__(self, history_db: AsyncRunPersistence) -> None:
        self._history_db = history_db

    async def load_report_request(
        self,
        run_id: str,
        requested_lang: str | None,
    ) -> HistoryReportRequest:
        run = await async_require_run(self._history_db, run_id)
        if run.status == RunStatus.ANALYZING:
            raise AnalysisNotReadyError("Analysis is still in progress", status="in_progress")
        if run.status == RunStatus.ERROR:
            raise AnalysisNotReadyError(str(run.error_message or "Analysis failed"), status="error")
        if run.analysis_corrupt:
            raise AnalysisNotReadyError(
                "Report data unavailable for this run. Re-analyze to regenerate the PDF."
            )
        analysis = run.analysis
        if analysis is None:
            raise AnalysisNotReadyError("No analysis available for this run")

        requested_lang = self._analysis_language(run, requested_lang)
        report_language = self._report_pdf_cache_lang(run, requested_lang)
        raw_warnings = analysis.get("warnings")
        warnings = raw_warnings if is_json_array(raw_warnings) else None
        cache_key = self._report_pdf_cache_key(
            run,
            run_id,
            report_language,
        )
        filename = f"{safe_filename(run_id)}_report.pdf"
        return HistoryReportRequest(
            prepared=prepare_persisted_report_input(
                analysis,
                warnings=warnings,
                filename=filename,
                language=report_language,
                cache_key=cache_key,
            ),
        )

    @staticmethod
    def _metadata_cache_token(metadata: RunMetadata) -> str:
        return json.dumps(
            run_metadata_to_json_object(metadata),
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        )

    def _report_pdf_cache_key(
        self,
        run: StoredHistoryRun,
        run_id: str,
        requested_lang: str,
    ) -> ReportPdfCacheKey:
        return (
            run_id,
            requested_lang,
            run.analysis_completed_at,
            run.sample_count,
            self._metadata_cache_token(run.metadata),
            _PERSISTED_REPORT_MODE_TOKEN,
        )

    @staticmethod
    def _report_pdf_cache_lang(run: StoredHistoryRun, requested_lang: str) -> str:
        analysis = run.analysis
        if analysis is not None:
            persisted_lang = analysis.language.strip().lower()
            if persisted_lang:
                return persisted_lang
        return requested_lang

    @staticmethod
    def _analysis_language(run: StoredHistoryRun, requested: str | None) -> str:
        return resolve_run_language(run, requested)
