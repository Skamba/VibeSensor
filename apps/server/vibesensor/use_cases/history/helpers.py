"""Shared helpers for history service workflows.

These helpers are framework-agnostic: they raise domain exceptions from
``vibesensor.shared.exceptions`` rather than HTTP-specific exceptions.  The
routes layer translates domain exceptions to HTTP status codes.
"""

from __future__ import annotations

import asyncio
import re
from typing import cast

from typing_extensions import TypedDict

from vibesensor.domain import RunStatus
from vibesensor.shared.exceptions import (
    AnalysisNotReadyError,
    DataCorruptError,
    RunNotFoundError,
)
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.json_types import JsonObject, is_json_object

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


class HistoryRecord(TypedDict, total=False):
    """History-run persistence record used only inside history workflows."""

    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None
    metadata: JsonObject
    analysis: JsonObject
    analysis_corrupt: bool
    error_message: str
    created_at: str
    sample_count: int
    analysis_started_at: str
    analysis_completed_at: str


def safe_filename(name: str) -> str:
    """Sanitize *name* for use in Content-Disposition headers and zip entry names."""
    cleaned = _SAFE_FILENAME_RE.sub("_", name)[:200].lstrip(".")
    return cleaned or "download"


def resolve_run_language(run: HistoryRecord, requested: str | None) -> str:
    """Resolve the effective language for a history run.

    Priority: explicit *requested* lang > run metadata ``language`` > ``"en"``.
    """
    if isinstance(requested, str) and requested.strip():
        return requested.strip().lower()
    metadata: object = run.get("metadata", {})
    if is_json_object(metadata):
        value = metadata.get("language")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return "en"


async def async_require_run(history_db: RunPersistence, run_id: str) -> HistoryRecord:
    """Fetch a history run in a thread or raise a domain exception."""
    run = await asyncio.to_thread(history_db.get_run, run_id)
    if run is None:
        raise RunNotFoundError(f"Run {run_id!r} not found")
    if not is_json_object(run):
        raise DataCorruptError(f"Run {run_id!r} data is corrupt")
    return cast("HistoryRecord", run)


def strip_internal_fields(analysis: JsonObject) -> JsonObject:
    """Return *analysis* without implementation-internal ``_``-prefixed keys."""
    return {key: value for key, value in analysis.items() if not key.startswith("_")}


def require_analysis_ready(run: HistoryRecord) -> JsonObject:
    """Return the analysis dict or raise a domain exception."""
    if run["status"] == RunStatus.ANALYZING:
        raise AnalysisNotReadyError("Analysis is still in progress", status="in_progress")
    if run["status"] == RunStatus.ERROR:
        raise AnalysisNotReadyError(
            str(run.get("error_message", "Analysis failed")),
            status="error",
        )
    analysis = run.get("analysis")
    if analysis is None:
        raise AnalysisNotReadyError("No analysis available for this run")
    return analysis
