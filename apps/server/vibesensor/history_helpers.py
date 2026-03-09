"""Shared helpers for history/read/report/export HTTP workflows."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException

from .backend_types import HistoryRunPayload
from .history_db import RunStatus
from .json_types import JsonObject, is_json_object

if TYPE_CHECKING:
    from .history_db import HistoryDB

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


def safe_filename(name: str) -> str:
    """Sanitize *name* for use in Content-Disposition headers and zip entry names."""
    cleaned = _SAFE_FILENAME_RE.sub("_", name)[:200].lstrip(".")
    return cleaned or "download"


async def async_require_run(history_db: HistoryDB, run_id: str) -> HistoryRunPayload:
    """Fetch a history run in a thread or raise 404."""
    run = await asyncio.to_thread(history_db.get_run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not is_json_object(run):
        raise HTTPException(status_code=500, detail="Run data is corrupt")
    return cast("HistoryRunPayload", run)


def strip_internal_fields(analysis: JsonObject) -> JsonObject:
    """Return *analysis* without implementation-internal ``_``-prefixed keys."""
    return {key: value for key, value in analysis.items() if not key.startswith("_")}


def require_analysis_ready(run: HistoryRunPayload) -> JsonObject:
    """Return the analysis dict or raise an appropriate HTTPException."""
    if run["status"] == RunStatus.ANALYZING:
        raise HTTPException(status_code=409, detail="Analysis is still in progress")
    if run["status"] == RunStatus.ERROR:
        raise HTTPException(
            status_code=422,
            detail=run.get("error_message", "Analysis failed"),
        )
    analysis = run.get("analysis")
    if analysis is None:
        raise HTTPException(status_code=422, detail="No analysis available for this run")
    return analysis
