"""History run/query service — framework-agnostic domain logic."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Never, cast

from vibesensor.adapters.persistence.boundaries._helpers import _has_structured_step_content
from vibesensor.adapters.persistence.boundaries.diagnostic_case import test_run_from_summary
from vibesensor.adapters.persistence.boundaries.finding import finding_payload_from_domain
from vibesensor.adapters.persistence.boundaries.run_suitability import run_suitability_payload
from vibesensor.adapters.persistence.boundaries.test_steps import step_payloads_from_plan
from vibesensor.adapters.persistence.boundaries.vibration_origin import origin_payload_from_finding
from vibesensor.adapters.persistence.history_db import RunStatus
from vibesensor.shared.errors import AnalysisNotReadyError, RunNotFoundError
from vibesensor.shared.types.backend import HistoryRunListEntryPayload, HistoryRunPayload
from vibesensor.shared.types.json import JsonObject, is_json_object
from vibesensor.use_cases.diagnostics.run_context import (
    add_current_context_warnings,
    localize_warning_list,
)

from .helpers import (
    async_require_run,
    require_analysis_ready,
    resolve_run_language,
    strip_internal_fields,
)

if TYPE_CHECKING:
    from vibesensor.adapters.persistence.history_db import HistoryDB
    from vibesensor.infra.config.settings_store import SettingsStore


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

    async def get_run(self, run_id: str) -> HistoryRunPayload:
        run = await async_require_run(self._history_db, run_id)
        analysis = run.get("analysis")
        if is_json_object(analysis):
            if isinstance(analysis.get("findings"), list) or isinstance(
                analysis.get("top_causes"), list
            ):
                test_run = test_run_from_summary(analysis)
                projected: JsonObject = dict(analysis)
                projected["findings"] = [finding_payload_from_domain(f) for f in test_run.findings]
                projected["top_causes"] = [
                    finding_payload_from_domain(f) for f in test_run.effective_top_causes()
                ]
                primary = test_run.primary_finding
                origin_fb = analysis.get("most_likely_origin")
                fb_payload = dict(origin_fb) if isinstance(origin_fb, Mapping) else {}
                projected["most_likely_origin"] = (
                    origin_payload_from_finding(primary, fb_payload)
                    if primary is not None
                    else fb_payload
                )
                if not _has_structured_step_content(analysis.get("test_plan")):
                    projected["test_plan"] = step_payloads_from_plan(test_run.test_plan)
                projected["run_suitability"] = run_suitability_payload(test_run.suitability)
                updated_run: HistoryRunPayload = {
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
            test_run = test_run_from_summary(raw_analysis)
            analysis["findings"] = [finding_payload_from_domain(f) for f in test_run.findings]
            analysis["top_causes"] = [
                finding_payload_from_domain(f) for f in test_run.effective_top_causes()
            ]
            primary = test_run.primary_finding
            origin_fb = raw_analysis.get("most_likely_origin")
            fb_payload = dict(origin_fb) if isinstance(origin_fb, Mapping) else {}
            analysis["most_likely_origin"] = (
                origin_payload_from_finding(primary, fb_payload)
                if primary is not None
                else fb_payload
            )
            if not _has_structured_step_content(raw_analysis.get("test_plan")):
                analysis["test_plan"] = step_payloads_from_plan(test_run.test_plan)
            analysis["run_suitability"] = run_suitability_payload(test_run.suitability)
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
