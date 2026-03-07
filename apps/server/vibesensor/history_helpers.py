"""Shared helpers for history/read/report/export HTTP workflows."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from .history_db import RunStatus

if TYPE_CHECKING:
    from .history_db import HistoryDB

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


def safe_filename(name: str) -> str:
    """Sanitize *name* for use in Content-Disposition headers and zip entry names."""
    cleaned = _SAFE_FILENAME_RE.sub("_", name)[:200].lstrip(".")
    return cleaned or "download"


async def async_require_run(history_db: HistoryDB, run_id: str) -> dict[str, Any]:
    """Fetch a history run in a thread or raise 404."""
    run = await asyncio.to_thread(history_db.get_run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def strip_internal_fields(analysis: dict[str, Any]) -> dict[str, Any]:
    """Return *analysis* without implementation-internal ``_``-prefixed keys."""
    return {key: value for key, value in analysis.items() if not key.startswith("_")}


def require_analysis_ready(run: dict[str, Any]) -> dict[str, Any]:
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
