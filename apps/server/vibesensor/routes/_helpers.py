"""Shared route helpers used across multiple route modules."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from ..domain_models import normalize_sensor_id

if TYPE_CHECKING:
    from ..history_db import HistoryDB

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


def normalize_client_id_or_400(client_id: str) -> str:
    """Normalize a client_id or raise HTTP 400."""
    try:
        return normalize_sensor_id(client_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid client_id") from exc


def safe_filename(name: str) -> str:
    """Sanitize *name* for use in Content-Disposition headers and zip entry names."""
    return _SAFE_FILENAME_RE.sub("_", name)[:200] or "download"


async def async_require_run(history_db: HistoryDB, run_id: str) -> dict[str, Any]:
    """Fetch a history run in a thread or raise 404."""
    run = await asyncio.to_thread(history_db.get_run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
