"""HTTP error mapping for domain and operational exceptions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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
    "http_status_for_analysis_not_ready_error",
    "http_exception_for_value_error",
    "http_exception_for_vibesensor_error",
    "install_http_exception_handlers",
    "http_status_for_operational_error",
    "route_errors_to_http",
]

_UNEXPECTED_ROUTE_ERROR_DETAIL = "Internal Server Error"


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


def http_status_for_analysis_not_ready_error(exc: AnalysisNotReadyError) -> int:
    """Return the HTTP status code for one analysis-readiness failure."""

    if exc.status in {"in_progress", "active"}:
        return 409
    if exc.status in {"error", "unavailable"}:
        return 422
    return 500


def http_exception_for_vibesensor_error(exc: VibeSensorError) -> HTTPException:
    """Convert one domain/runtime error into an HTTPException."""

    if isinstance(exc, RunNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AnalysisNotReadyError):
        return HTTPException(
            status_code=http_status_for_analysis_not_ready_error(exc),
            detail=str(exc),
        )
    if isinstance(exc, (ConfigurationError, ProtocolError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, UpdateError):
        status_code = 409 if exc.status == "conflict" else 500
        return HTTPException(status_code=status_code, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def http_exception_for_value_error(
    exc: ValueError,
    *,
    status_code: int,
) -> HTTPException:
    """Convert one explicitly handled request-validation ValueError into HTTP."""
    return HTTPException(status_code=status_code, detail=str(exc))


def _json_response_for_http_exception(exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def install_http_exception_handlers(app: FastAPI) -> None:
    """Install explicit HTTP exception handlers at the FastAPI boundary."""

    async def _operational_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        if not isinstance(exc, OperationalError):
            raise TypeError(f"Expected OperationalError handler input, got {type(exc).__name__}")
        return _json_response_for_http_exception(http_exception_for_operational_error(exc))

    async def _domain_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        if not isinstance(exc, VibeSensorError):
            raise TypeError(f"Expected VibeSensorError handler input, got {type(exc).__name__}")
        return _json_response_for_http_exception(http_exception_for_vibesensor_error(exc))

    app.add_exception_handler(OperationalError, _operational_handler)
    app.add_exception_handler(VibeSensorError, _domain_handler)


@contextmanager
def route_errors_to_http() -> Iterator[None]:
    """Translate route-facing domain and operational errors into HTTP responses."""

    try:
        yield
    except VibeSensorError as exc:
        raise http_exception_for_vibesensor_error(exc) from exc
    except OperationalError as exc:
        raise http_exception_for_operational_error(exc) from exc
    except HTTPException:
        raise
    except ValueError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_UNEXPECTED_ROUTE_ERROR_DETAIL) from exc
