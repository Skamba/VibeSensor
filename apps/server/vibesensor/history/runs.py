"""History run/query service — framework-agnostic domain logic."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Never

from vibesensor.common.exceptions import AnalysisNotReadyError, RunNotFoundError
from vibesensor.common.json_types import JsonObject
from vibesensor.domain.run_status import RunStatus
from vibesensor.history.helpers import (
    async_require_run,
    require_analysis_ready,
    strip_internal_fields,
)
from vibesensor.history.records import HistoryRunListEntry, StoredHistoryRun

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB


class HistoryRunService:
    """Run queries and delete operations used by history endpoints."""

    __slots__ = ("_history_db",)

    def __init__(self, history_db: HistoryDB) -> None:
        self._history_db = history_db

    async def list_runs(self) -> list[HistoryRunListEntry]:
        return await asyncio.to_thread(self._history_db.list_runs)

    async def get_run(self, run_id: str) -> StoredHistoryRun:
        return await async_require_run(self._history_db, run_id)

    async def get_insights(self, run_id: str) -> JsonObject | None:
        """Return a run's stored analysis for the insights response, or ``None`` if still analyzing.

        Its warnings stay unlocalized: the HTTP projection words them in the
        requested language, after building the report's owner page from them.
        """
        run = await async_require_run(self._history_db, run_id)
        if (
            run.lifecycle is not None
            and run.lifecycle.stage != "recording"
            and run.lifecycle.post_analysis in {"pending", "running"}
        ):
            return None
        if run.status == RunStatus.ANALYZING:
            return None

        raw_analysis = require_analysis_ready(run)
        analysis = strip_internal_fields(raw_analysis.payload)
        analysis["run_id"] = run.run_id or run_id
        analysis["status"] = RunStatus.COMPLETE.value
        return analysis

    async def delete_run(self, run_id: str) -> dict[str, str]:
        deleted, reason = await asyncio.to_thread(self._history_db.delete_run_if_safe, run_id)
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
