"""Shared route helpers used across multiple route modules."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

from ..exceptions import (
    AnalysisNotReadyError,
    DataCorruptError,
    ProcessingError,
    RunNotFoundError,
)
from ..history_services.helpers import async_require_run, safe_filename
from ..protocol import normalize_sensor_id

__all__ = [
    "async_require_run",
    "domain_errors_to_http",
    "normalize_client_id_or_400",
    "normalize_mac_or_400",
    "safe_filename",
]


@contextmanager
def domain_errors_to_http() -> Iterator[None]:
    """Translate domain exceptions to appropriate HTTP status codes.

    This is the single place in the routes layer where domain exceptions
    from the service layer are mapped to ``HTTPException`` responses.
    """
    try:
        yield
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnalysisNotReadyError as exc:
        status_map = {"in_progress": 409, "active": 409, "error": 422, "unavailable": 422}
        raise HTTPException(
            status_code=status_map.get(exc.status, 409),
            detail=str(exc),
        ) from exc
    except DataCorruptError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ProcessingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
