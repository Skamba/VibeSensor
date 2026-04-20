"""History run/query service — framework-agnostic domain logic."""

from __future__ import annotations

import asyncio
from typing import Never, cast

from vibesensor.domain import RunStatus
from vibesensor.shared.boundaries.summary_fields.warnings import localize_warning_list
from vibesensor.shared.exceptions import AnalysisNotReadyError, RunNotFoundError
from vibesensor.shared.ports import AsyncRunPersistence, RunPersistence
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

    def __init__(self, history_db: AsyncRunPersistence) -> None:
        self._history_db = history_db

    async def list_runs(self) -> list[HistoryRunListEntry]:
        alist_runs = getattr(self._history_db, "alist_runs", None)
        if callable(alist_runs):
            return cast(list[HistoryRunListEntry], await alist_runs())
        sync_history_db = cast(RunPersistence, self._history_db)
        return await asyncio.to_thread(sync_history_db.list_runs)

    async def get_run(self, run_id: str) -> StoredHistoryRun:
        return await async_require_run(self._history_db, run_id)

    async def get_insights(
        self,
        run_id: str,
        requested_lang: str | None = None,
    ) -> JsonObject | None:
        """Return analysis insights for a run, or ``None`` if still analyzing."""
        run = await async_require_run(self._history_db, run_id)
        if run.status == RunStatus.ANALYZING:
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

        return analysis

    async def delete_run(self, run_id: str) -> dict[str, str]:
        adelete_run_if_safe = getattr(self._history_db, "adelete_run_if_safe", None)
        if callable(adelete_run_if_safe):
            deleted, reason = await adelete_run_if_safe(run_id)
        else:
            sync_history_db = cast(RunPersistence, self._history_db)
            deleted, reason = await asyncio.to_thread(sync_history_db.delete_run_if_safe, run_id)
        if deleted:
            return {"run_id": run_id, "status": "deleted"}
        raise_delete_run_error(reason)


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
