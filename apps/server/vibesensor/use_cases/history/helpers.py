"""Shared helpers for history service workflows.

These helpers are framework-agnostic: they raise domain exceptions from
``vibesensor.shared.exceptions`` rather than HTTP-specific exceptions.  The
routes layer translates domain exceptions to HTTP status codes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from vibesensor.domain import RunStatus
from vibesensor.shared.exceptions import (
    AnalysisNotReadyError,
    RunNotFoundError,
)
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis


def resolve_run_language(run: StoredHistoryRun, requested: str | None) -> str:
    """Resolve the effective language for a history run.

    Priority: explicit *requested* lang > run metadata ``language`` > ``"en"``.
    """
    if isinstance(requested, str) and requested.strip():
        return requested.strip().lower()
    return run.metadata.language or "en"


async def async_require_run(history_db: RunPersistence, run_id: str) -> StoredHistoryRun:
    """Fetch a history run or raise a domain exception."""
    run = await history_db.aget_run(run_id)
    if run is None:
        raise RunNotFoundError(f"Run {run_id!r} not found")
    return run


def strip_internal_fields(analysis: Mapping[str, object]) -> JsonObject:
    """Return *analysis* without implementation-internal ``_``-prefixed keys."""
    return cast(
        JsonObject,
        {key: value for key, value in analysis.items() if not key.startswith("_")},
    )


def require_analysis_ready(run: StoredHistoryRun) -> PersistedAnalysis:
    """Return the internal persisted-analysis object or raise a domain exception."""
    if run.status == RunStatus.ANALYZING:
        raise AnalysisNotReadyError("Analysis is still in progress", status="in_progress")
    if run.status == RunStatus.ERROR:
        raise AnalysisNotReadyError(
            str(run.error_message or "Analysis failed"),
            status="error",
        )
    analysis = run.analysis
    if analysis is None:
        raise AnalysisNotReadyError("No analysis available for this run")
    return analysis
