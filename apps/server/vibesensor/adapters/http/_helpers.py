"""Shared route helpers used across multiple route modules."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException

from vibesensor.domain import normalize_sensor_id
from vibesensor.shared.exceptions import (
    AnalysisNotReadyError,
    ConfigurationError,
    DataCorruptError,
    ProcessingError,
    ProtocolError,
    RunNotFoundError,
    UpdateError,
    VibeSensorError,
)
from vibesensor.use_cases.history.helpers import async_require_run, safe_filename

__all__ = [
    "OpenAPIResponses",
    "async_require_run",
    "domain_errors_to_http",
    "normalize_car_id_or_400",
    "normalize_client_id_or_400",
    "normalize_mac_or_400",
    "normalize_run_id_or_400",
    "safe_filename",
]

type OpenAPIResponses = dict[int | str, dict[str, Any]]
_CAR_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_RUN_ID_RE = re.compile(r"^[!-~]{1,128}$")


@contextmanager
def domain_errors_to_http(
    *,
    catch_value_error: int | None = None,
    catch_runtime_error: int | None = None,
) -> Iterator[None]:
    """Translate domain exceptions to appropriate HTTP status codes.

    This is the single place in the routes layer where domain exceptions
    from the service layer are mapped to ``HTTPException`` responses.

    Optional parameters allow catching ``ValueError`` / ``RuntimeError``
    with a caller-specified HTTP status code.
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
    except ConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProtocolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UpdateError as exc:
        status_code = 409 if exc.status == "conflict" else 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except DataCorruptError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ProcessingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except VibeSensorError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        if catch_value_error is None:
            raise
        raise HTTPException(status_code=catch_value_error, detail=str(exc)) from exc
    except RuntimeError as exc:
        if catch_runtime_error is None:
            raise
        raise HTTPException(status_code=catch_runtime_error, detail=str(exc)) from exc


def normalize_client_id_or_400(client_id: str) -> str:
    """Normalize a client_id or raise HTTP 400."""
    try:
        return normalize_sensor_id(client_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid sensor identifier") from exc


def normalize_run_id_or_400(run_id: str) -> str:
    """Validate a history run identifier or raise HTTP 400."""
    if _RUN_ID_RE.fullmatch(run_id):
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
