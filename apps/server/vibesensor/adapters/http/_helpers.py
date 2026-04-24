"""Shared route helpers used across multiple route modules."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from vibesensor.domain import normalize_sensor_id
from vibesensor.shared.filenames import safe_filename
from vibesensor.use_cases.history.helpers import async_require_run

__all__ = [
    "OpenAPIResponses",
    "async_require_run",
    "normalize_car_id_or_400",
    "normalize_client_id_or_400",
    "normalize_mac_or_400",
    "normalize_run_id_or_400",
    "safe_filename",
]

type OpenAPIResponses = dict[int | str, dict[str, Any]]
_CAR_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def normalize_client_id_or_400(client_id: str) -> str:
    """Normalize a client_id or raise HTTP 400."""
    try:
        return normalize_sensor_id(client_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid sensor identifier") from exc


def normalize_run_id_or_400(run_id: str) -> str:
    """Validate a history run identifier or raise HTTP 400."""
    if _RUN_ID_RE.fullmatch(run_id) and ".." not in run_id:
        return run_id
    raise HTTPException(status_code=400, detail="Invalid run identifier")


def normalize_car_id_or_400(car_id: str) -> str:
    """Validate a car configuration identifier or raise HTTP 400."""
    if _CAR_ID_RE.fullmatch(car_id):
        return car_id
    raise HTTPException(status_code=400, detail="Invalid car identifier")


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
