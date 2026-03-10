"""History run/query service — framework-agnostic domain logic."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Never, cast

from ..backend_types import HistoryRunListEntryPayload, HistoryRunPayload
from ..exceptions import AnalysisNotReadyError, RunNotFoundError
from ..history_db import RunStatus
from ..json_types import JsonObject, is_json_object
from ..run_context import add_current_context_warnings, localize_warning_list
from .helpers import async_require_run, require_analysis_ready, strip_internal_fields

if TYPE_CHECKING:
    from ..history_db import HistoryDB
    from ..settings_store import SettingsStore


@dataclass(frozen=True)
class HistoryJsonResult:
    """JSON-serialisable result with an explicit HTTP status."""

    status_code: int
    payload: JsonObject


class HistoryRunService:
    """Load, sanitise, and mutate history-run resources for HTTP endpoints."""

    __slots__ = ("_history_db", "_settings_store")

    def __init__(self, history_db: HistoryDB, settings_store: SettingsStore | None = None) -> None:
        self._history_db = history_db
        self._settings_store = settings_store


class HistoryRunQueryService(HistoryRunService):
    """Read-only run queries used by history endpoints."""

    async def list_runs(self) -> list[HistoryRunListEntryPayload]:
        return cast(
            "list[HistoryRunListEntryPayload]",
            await asyncio.to_thread(self._history_db.list_runs),
        )

    async def get_run(self, run_id: str) -> HistoryRunPayload:
        run = await async_require_run(self._history_db, run_id)
        analysis = run.get("analysis")
        if is_json_object(analysis):
            updated_run: HistoryRunPayload = {**run, "analysis": strip_internal_fields(analysis)}
            return updated_run
        return run

    async def get_insights(
        self,
        run_id: str,
        requested_lang: str | None = None,
    ) -> HistoryJsonResult:
        run = await async_require_run(self._history_db, run_id)
        if run["status"] == RunStatus.ANALYZING:
            return HistoryJsonResult(
                status_code=202,
                payload={"run_id": run_id, "status": RunStatus.ANALYZING},
            )

        analysis = require_analysis_ready(run)
        active_car_snapshot = (
            getattr(self._settings_store, "active_car_snapshot", None)
            if self._settings_store is not None
            else None
        )
        current_active_car_snapshot = (
            active_car_snapshot() if callable(active_car_snapshot) else None
        )
        analysis = add_current_context_warnings(
            analysis,
            current_active_car_snapshot=current_active_car_snapshot,
        )
        analysis_is_current = getattr(self._history_db, "analysis_is_current", None)
        if callable(analysis_is_current):
            analysis["analysis_is_current"] = await asyncio.to_thread(
                analysis_is_current,
                run_id,
            )
        else:
            analysis["analysis_is_current"] = False
        metadata: object = run.get("metadata")
        response_lang = requested_lang if isinstance(requested_lang, str) else None
        if response_lang is None and is_json_object(metadata):
            raw_lang = metadata.get("language")
            if isinstance(raw_lang, str) and raw_lang.strip():
                response_lang = raw_lang.strip().lower()
        localized_warnings = localize_warning_list(
            analysis.get("warnings"),
            lang=response_lang or "en",
        )
        analysis["warnings"] = list(localized_warnings)

        return HistoryJsonResult(status_code=200, payload=strip_internal_fields(analysis))


class HistoryRunDeleteService(HistoryRunService):
    """Delete-policy adapter for history runs."""

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
    if reason == RunStatus.ANALYZING:
        raise AnalysisNotReadyError(
            "Cannot delete run while analysis is in progress",
            status="in_progress",
        )
    raise AnalysisNotReadyError("Cannot delete run at this time", status="active")
