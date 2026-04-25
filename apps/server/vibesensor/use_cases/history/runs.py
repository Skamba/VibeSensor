"""History run/query service — framework-agnostic domain logic."""

from __future__ import annotations

from typing import Never, cast

from opentelemetry.trace import SpanKind

from vibesensor.domain import RunStatus
from vibesensor.shared.boundaries.summary_fields.warnings import localize_warning_list
from vibesensor.shared.exceptions import AnalysisNotReadyError, RunNotFoundError
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.shared.types.history_records import HistoryRunListEntry, StoredHistoryRun
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_array
from vibesensor.use_cases.history.helpers import (
    async_require_run,
    require_analysis_ready,
    resolve_run_language,
    strip_internal_fields,
)


class HistoryRunService:
    """Run queries and delete operations used by history endpoints."""

    __slots__ = ("_history_db",)

    def __init__(self, history_db: RunPersistence) -> None:
        self._history_db = history_db

    async def list_runs(self) -> list[HistoryRunListEntry]:
        with start_span(__name__, "history.runs.list", kind=SpanKind.INTERNAL) as span:
            try:
                runs = await self._history_db.alist_runs()
            except Exception as exc:
                mark_span_error(span, exc)
                raise
            span.set_attribute("vibesensor.run_count", len(runs))
            return runs

    async def get_run(self, run_id: str) -> StoredHistoryRun:
        with start_span(
            __name__,
            "history.run.get",
            kind=SpanKind.INTERNAL,
            attributes={"vibesensor.run_id": run_id},
        ) as span:
            try:
                run = await async_require_run(self._history_db, run_id)
            except Exception as exc:
                mark_span_error(span, exc)
                raise
            span.set_attribute("vibesensor.run_status", run.status.value)
            return run

    async def get_insights(
        self,
        run_id: str,
        requested_lang: str | None = None,
    ) -> JsonObject | None:
        """Return analysis insights for a run, or ``None`` if still analyzing."""
        with start_span(
            __name__,
            "history.run.insights",
            kind=SpanKind.INTERNAL,
            attributes={
                "vibesensor.run_id": run_id,
                "vibesensor.requested_lang": requested_lang or "",
            },
        ) as span:
            try:
                run = await async_require_run(self._history_db, run_id)
                if run.lifecycle is not None and run.lifecycle.post_analysis in {
                    "pending",
                    "running",
                }:
                    span.set_attribute("vibesensor.analysis_ready", False)
                    return None
                if run.status == RunStatus.ANALYZING:
                    span.set_attribute("vibesensor.analysis_ready", False)
                    return None

                raw_analysis = require_analysis_ready(run)
                analysis = strip_internal_fields(raw_analysis.payload)
                response_lang = resolve_run_language(run, requested_lang)
                raw_warnings = analysis.get("warnings")
                analysis["warnings"] = cast(
                    JsonValue,
                    localize_warning_list(
                        raw_warnings if is_json_array(raw_warnings) else None,
                        lang=response_lang,
                    ),
                )
                analysis["run_id"] = run.run_id or run_id
                analysis["status"] = RunStatus.COMPLETE.value
            except Exception as exc:
                mark_span_error(span, exc)
                raise
            span.set_attribute("vibesensor.analysis_ready", True)
            span.set_attribute("vibesensor.response_lang", response_lang)
            return analysis

    async def delete_run(self, run_id: str) -> dict[str, str]:
        with start_span(
            __name__,
            "history.run.delete",
            kind=SpanKind.INTERNAL,
            attributes={"vibesensor.run_id": run_id},
        ) as span:
            try:
                deleted, reason = await self._history_db.adelete_run_if_safe(run_id)
                if deleted:
                    span.set_attribute("vibesensor.deleted", True)
                    return {"run_id": run_id, "status": "deleted"}
                span.set_attribute("vibesensor.deleted", False)
                span.set_attribute("vibesensor.delete_reason", reason or "")
                raise_delete_run_error(reason)
            except Exception as exc:
                mark_span_error(span, exc)
                raise


def raise_delete_run_error(reason: str | None) -> Never:
    """Raise the domain error for a failed delete attempt."""
    if reason == "not_found":
        raise RunNotFoundError("Run not found")
    if reason == "active":
        raise AnalysisNotReadyError(
            "Cannot delete the active run; stop recording first",
            status="active",
        )
    if reason == RunStatus.ANALYZING.value:
        raise AnalysisNotReadyError(
            "Cannot delete run while analysis is in progress",
            status="in_progress",
        )
    raise AnalysisNotReadyError("Cannot delete run at this time", status="active")
