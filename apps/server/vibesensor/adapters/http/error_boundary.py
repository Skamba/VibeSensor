"""HTTP error mapping for domain and operational exceptions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

from vibesensor.shared.exceptions import (
    AnalysisNotReadyError,
    ConfigurationError,
    ProtocolError,
    RunNotFoundError,
    UpdateError,
    VibeSensorError,
)
from vibesensor.shared.operational_errors import OperationalError, ServiceUnavailableError

__all__ = [
    "http_exception_for_operational_error",
    "http_status_for_operational_error",
    "route_errors_to_http",
]


def http_status_for_operational_error(exc: OperationalError) -> int:
    """Return the HTTP status code for one operational failure."""

    if isinstance(exc, ServiceUnavailableError):
        return 503
    return 500


def http_exception_for_operational_error(exc: OperationalError) -> HTTPException:
    """Convert one operational failure into an HTTPException."""

    return HTTPException(
        status_code=http_status_for_operational_error(exc),
        detail=str(exc),
    )


@contextmanager
def route_errors_to_http(*, catch_value_error: int | None = None) -> Iterator[None]:
    """Translate route-facing domain and operational errors into HTTP responses."""

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
    except VibeSensorError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except OperationalError as exc:
        raise http_exception_for_operational_error(exc) from exc
    except ValueError as exc:
        if catch_value_error is None:
            raise
        raise HTTPException(status_code=catch_value_error, detail=str(exc)) from exc
