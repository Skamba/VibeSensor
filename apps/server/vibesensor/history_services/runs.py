"""History run/query service — framework-agnostic domain logic."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Never, cast

from ..backend_types import HistoryRunListEntryPayload, HistoryRunPayload
from ..domain import HistoryRecord
from ..exceptions import AnalysisNotReadyError, RunNotFoundError
from ..history_db import RunStatus
from ..json_types import JsonObject, is_json_object
from ..run_context import add_current_context_warnings, localize_warning_list
from .helpers import async_require_run, require_analysis_ready, strip_internal_fields

if TYPE_CHECKING:
    from ..history_db import HistoryDB
    from ..settings_store import SettingsStore


class HistoryRunService:
    """Run queries and delete operations used by history endpoints."""

    __slots__ = ("_history_db", "_settings_store")

    def __init__(self, history_db: HistoryDB, settings_store: SettingsStore | None = None) -> None:
        self._history_db = history_db
        self._settings_store = settings_store

    async def list_runs(self) -> list[HistoryRunListEntryPayload]:
        return cast(
            "list[HistoryRunListEntryPayload]",
            await asyncio.to_thread(self._history_db.list_runs),
        )

    async def list_history_records(self) -> list[HistoryRecord]:
        """Return all runs as domain ``HistoryRecord`` value objects."""
        raw_runs = await asyncio.to_thread(self._history_db.list_runs)
        return [_to_history_record(r) for r in raw_runs]

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
    ) -> JsonObject | None:
        """Return analysis insights for a run, or ``None`` if still analyzing."""
        run = await async_require_run(self._history_db, run_id)
        if run["status"] == RunStatus.ANALYZING:
            return None

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

        return strip_internal_fields(analysis)

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


def _to_history_record(raw: JsonObject) -> HistoryRecord:
    """Convert a raw history DB dict to a domain ``HistoryRecord``."""
    end_time = raw.get("end_time_utc")
    error_msg = raw.get("error_message")
    raw_count = raw.get("sample_count")
    status_str = str(raw.get("status", ""))
    return HistoryRecord(
        run_id=str(raw.get("run_id", "")),
        status=RunStatus(status_str) if status_str else RunStatus.RECORDING,
        start_time_utc=str(raw.get("start_time_utc", "")),
        end_time_utc=str(end_time) if isinstance(end_time, str) else None,
        sample_count=int(raw_count) if isinstance(raw_count, int) else 0,
        error_message=str(error_msg) if error_msg else None,
    )
