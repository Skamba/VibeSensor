"""History run/query service — framework-agnostic domain logic."""

from __future__ import annotations

import asyncio
from typing import Never

from vibesensor.domain import RunStatus
from vibesensor.shared.boundaries.diagnostic_case import project_analysis_summary
from vibesensor.shared.exceptions import AnalysisNotReadyError, RunNotFoundError
from vibesensor.shared.run_context import add_current_context_warnings, localize_warning_list
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.shared.types.run_persistence import RunPersistence
from vibesensor.shared.types.settings_reader import SettingsReader
from vibesensor.use_cases.history.helpers import (
    HistoryRecord,
    async_require_run,
    require_analysis_ready,
    resolve_run_language,
    strip_internal_fields,
)


class HistoryRunService:
    """Run queries and delete operations used by history endpoints."""

    __slots__ = ("_history_db", "_settings_store")

    def __init__(
        self,
        history_db: RunPersistence,
        settings_store: SettingsReader | None = None,
    ) -> None:
        self._history_db = history_db
        self._settings_store = settings_store

    async def list_runs(self) -> list[JsonObject]:
        return await asyncio.to_thread(self._history_db.list_runs)

    async def get_run(self, run_id: str) -> HistoryRecord:
        run = await async_require_run(self._history_db, run_id)
        analysis = run.get("analysis")
        if is_json_object(analysis):
            if isinstance(analysis.get("findings"), list) or isinstance(
                analysis.get("top_causes"), list
            ):
                projected, _ = project_analysis_summary(analysis)
                updated_run: HistoryRecord = {
                    **run,
                    "analysis": strip_internal_fields(projected),
                }
                return updated_run
            return {**run, "analysis": strip_internal_fields(dict(analysis))}
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

        raw_analysis = require_analysis_ready(run)
        analysis: JsonObject = dict(raw_analysis)
        if isinstance(raw_analysis.get("findings"), list) or isinstance(
            raw_analysis.get("top_causes"), list
        ):
            analysis, _ = project_analysis_summary(raw_analysis)
        current_active_car_snapshot = (
            self._settings_store.active_car_snapshot() if self._settings_store is not None else None
        )
        analysis = add_current_context_warnings(
            analysis,
            current_active_car_snapshot=current_active_car_snapshot,
        )
        response_lang = resolve_run_language(run, requested_lang)
        localized_warnings = localize_warning_list(
            analysis.get("warnings"),
            lang=response_lang,
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
