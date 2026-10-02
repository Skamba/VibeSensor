"""Persisted history-report loading and canonical prepared-report handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from vibesensor.common.filenames import safe_filename
from vibesensor.common.json_types import is_json_array
from vibesensor.common.json_utils import json_text_dumps
from vibesensor.recording.run_metadata import run_metadata_to_json_object
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.report.cache_key import ReportPdfCacheKey
from vibesensor.report.input import PreparedReportInput
from vibesensor.report.preparation import prepare_persisted_report_input
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.summary.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.helpers import (
    async_require_run,
    require_analysis_ready,
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

    def __init__(self, history_db: RunPersistence) -> None:
        self._history_db = history_db

    async def load_report_request(
        self,
        run_id: str,
        requested_lang: str | None,
    ) -> HistoryReportRequest:
        run = await async_require_run(self._history_db, run_id)
        analysis = require_analysis_ready(run)
        analysis_for_report = self._analysis_with_report_metadata(
            analysis,
            run.metadata,
        )

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
                analysis_for_report,
                warnings=warnings,
                filename=filename,
                language=report_language,
                cache_key=cache_key,
            ),
        )

    @staticmethod
    def _metadata_cache_token(metadata: RunMetadata) -> str:
        return json_text_dumps(
            run_metadata_to_json_object(metadata),
            sort_keys=True,
        )

    @staticmethod
    def _analysis_cache_token(analysis: object) -> str:
        if hasattr(analysis, "to_json_object"):
            analysis_payload = analysis.to_json_object()
        else:
            analysis_payload = analysis
        encoded = json_text_dumps(analysis_payload, sort_keys=True).encode("utf-8")
        return sha256(encoded).hexdigest()

    @staticmethod
    def _analysis_with_report_metadata(
        analysis: PersistedAnalysis,
        metadata: RunMetadata,
    ) -> PersistedAnalysis:
        if not metadata.finalization_stages:
            return analysis
        payload = analysis.to_json_object()
        metadata_payload = payload.get("metadata")
        current_metadata = dict(metadata_payload) if isinstance(metadata_payload, Mapping) else {}
        run_metadata_payload = run_metadata_to_json_object(metadata)
        finalization_stages = run_metadata_payload.get("finalization_stages")
        if finalization_stages is None:
            return analysis
        payload["metadata"] = {
            **current_metadata,
            "run_id": current_metadata.get("run_id") or metadata.run_id,
            "finalization_stages": finalization_stages,
        }
        return PersistedAnalysis.from_json_object(payload)

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
            self._analysis_cache_token(run.analysis),
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
