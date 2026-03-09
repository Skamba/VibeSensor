"""Shared route helpers used across multiple route modules."""

from __future__ import annotations

from fastapi import HTTPException

from ..domain_models import normalize_sensor_id
from ..history_helpers import async_require_run, safe_filename

__all__ = [
    "async_require_run",
    "normalize_client_id_or_400",
    "normalize_mac_or_400",
    "safe_filename",
]


def normalize_client_id_or_400(client_id: str) -> str:
    """Normalize a client_id or raise HTTP 400."""
    try:
        return normalize_sensor_id(client_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid sensor identifier") from exc


def normalize_mac_or_400(mac: str) -> str:
    """Normalize a MAC address path parameter or raise HTTP 400 with a clear message.

    Performs an early length guard before delegating to normalize_sensor_id,
    so that oversized or empty inputs are rejected without touching the store.
    """
    if not mac or len(mac) > 64:
        raise HTTPException(status_code=400, detail="Invalid MAC address: must be 1-64 characters")
    try:
        return normalize_sensor_id(mac)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid MAC address format") from exc
