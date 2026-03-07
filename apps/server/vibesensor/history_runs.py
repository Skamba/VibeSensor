"""History run/query service for the HTTP layer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from .history_db import ANALYSIS_SCHEMA_VERSION, RunStatus
from .history_helpers import async_require_run, require_analysis_ready, strip_internal_fields

if TYPE_CHECKING:
    from .history_db import HistoryDB


@dataclass(frozen=True)
class HistoryJsonResult:
    """JSON-serialisable result with an explicit HTTP status."""

    status_code: int
    payload: dict[str, Any]


class HistoryRunService:
    """Load, sanitise, and mutate history-run resources for HTTP endpoints."""

    __slots__ = ("_history_db",)

    def __init__(self, history_db: HistoryDB) -> None:
        self._history_db = history_db


class HistoryRunQueryService(HistoryRunService):
    """Read-only run queries used by history endpoints."""

    async def list_runs(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._history_db.list_runs)

    async def get_run(self, run_id: str) -> dict[str, Any]:
        run = await async_require_run(self._history_db, run_id)
        analysis = run.get("analysis")
        if isinstance(analysis, dict):
            run = dict(run)
            run["analysis"] = strip_internal_fields(analysis)
        return run

    async def get_insights(self, run_id: str) -> HistoryJsonResult:
        run = await async_require_run(self._history_db, run_id)
        if run["status"] == RunStatus.ANALYZING:
            return HistoryJsonResult(
                status_code=202,
                payload={"run_id": run_id, "status": RunStatus.ANALYZING},
            )

        analysis = require_analysis_ready(run)
        if isinstance(analysis, dict):
            analysis = dict(analysis)
            analysis["analysis_is_current"] = self._analysis_is_current(run.get("analysis_version"))
            analysis = strip_internal_fields(analysis)

        return HistoryJsonResult(status_code=200, payload=analysis)

    @staticmethod
    def _analysis_is_current(analysis_version: object) -> bool:
        try:
            return (
                int(analysis_version) >= ANALYSIS_SCHEMA_VERSION
                if analysis_version is not None
                else False
            )
        except (TypeError, ValueError):
            return False


class HistoryRunDeleteService(HistoryRunService):
    """Delete-policy adapter for history runs."""

    async def delete_run(self, run_id: str) -> dict[str, str]:
        deleted, reason = await asyncio.to_thread(self._history_db.delete_run_if_safe, run_id)
        if deleted:
            return {"run_id": run_id, "status": "deleted"}
        raise_delete_run_error(reason)


def raise_delete_run_error(reason: str | None) -> None:
    """Raise the public HTTP error for a failed delete attempt."""
    if reason == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    if reason == "active":
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the active run; stop recording first",
        )
    if reason == RunStatus.ANALYZING:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete run while analysis is in progress",
        )
    raise HTTPException(status_code=409, detail="Cannot delete run at this time")
