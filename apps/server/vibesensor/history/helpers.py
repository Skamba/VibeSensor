"""Shared helpers for history service workflows.

These helpers are framework-agnostic: they raise domain exceptions from
``vibesensor.common.exceptions`` rather than HTTP-specific exceptions.  The
routes layer translates domain exceptions to HTTP status codes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from vibesensor.common.exceptions import (
    AnalysisNotReadyError,
    RunNotFoundError,
)
from vibesensor.common.json_types import JsonObject
from vibesensor.domain.run_status import RunStatus
from vibesensor.history.records import StoredHistoryRun
from vibesensor.summary.persisted_analysis import PersistedAnalysis

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB


def resolve_run_language(run: StoredHistoryRun, requested: str | None) -> str:
    """Resolve the effective language for a history run.

    Priority: explicit *requested* lang > run metadata ``language`` > ``"en"``.
    """
    if isinstance(requested, str) and requested.strip():
        return requested.strip().lower()
    return run.metadata.language or "en"


async def async_require_run(history_db: HistoryDB, run_id: str) -> StoredHistoryRun:
    """Fetch a history run or raise a domain exception."""
    run = await asyncio.to_thread(history_db.get_run, run_id)
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
    lifecycle = run.lifecycle
    if (
        lifecycle is not None
        and lifecycle.stage != "recording"
        and lifecycle.post_analysis in {"pending", "running"}
    ):
        raise AnalysisNotReadyError("Analysis is still in progress", status="in_progress")
    if run.status == RunStatus.RECORDING:
        raise AnalysisNotReadyError(
            "Analysis is not available while recording is still active",
        )
    if run.status == RunStatus.ANALYZING:
        raise AnalysisNotReadyError("Analysis is still in progress", status="in_progress")
    if run.status == RunStatus.ERROR:
        raise AnalysisNotReadyError(
            str(run.error_message or "Analysis failed"),
            status="error",
        )
    if run.analysis_corrupt:
        raise AnalysisNotReadyError(
            "Report data unavailable for this run. Re-analyze to regenerate the PDF."
        )
    analysis = run.analysis
    if analysis is None:
        raise AnalysisNotReadyError("No analysis available for this run")
    return analysis
