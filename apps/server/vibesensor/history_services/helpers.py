"""Shared helpers for history service workflows.

These helpers are framework-agnostic: they raise domain exceptions from
``vibesensor.exceptions`` rather than HTTP-specific exceptions.  The
routes layer translates domain exceptions to HTTP status codes.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, cast

from ..backend_types import HistoryRunPayload
from ..exceptions import AnalysisNotReadyError, DataCorruptError, RunNotFoundError
from ..history_db import RunStatus
from ..json_types import JsonObject, is_json_object

if TYPE_CHECKING:
    from ..history_db import HistoryDB

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


def safe_filename(name: str) -> str:
    """Sanitize *name* for use in Content-Disposition headers and zip entry names."""
    cleaned = _SAFE_FILENAME_RE.sub("_", name)[:200].lstrip(".")
    return cleaned or "download"


async def async_require_run(history_db: HistoryDB, run_id: str) -> HistoryRunPayload:
    """Fetch a history run in a thread or raise a domain exception."""
    run = await asyncio.to_thread(history_db.get_run, run_id)
    if run is None:
        raise RunNotFoundError(f"Run {run_id!r} not found")
    if not is_json_object(run):
        raise DataCorruptError(f"Run {run_id!r} data is corrupt")
    return cast("HistoryRunPayload", run)


def strip_internal_fields(analysis: JsonObject) -> JsonObject:
    """Return *analysis* without implementation-internal ``_``-prefixed keys."""
    return {key: value for key, value in analysis.items() if not key.startswith("_")}


def require_analysis_ready(run: HistoryRunPayload) -> JsonObject:
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
