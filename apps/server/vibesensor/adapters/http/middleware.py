from __future__ import annotations

import asyncio
import logging
import sys
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import FastAPI
from opentelemetry.trace import SpanKind
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vibesensor.shared.exceptions import VibeSensorError
from vibesensor.shared.operational_errors import OperationalError
from vibesensor.shared.structured_logging import (
    REQUEST_ID_HEADER,
    bind_request_id,
    current_request_id,
    log_extra,
    reset_request_id,
)
from vibesensor.shared.tracing import mark_span_error, start_span

LOGGER = logging.getLogger(__name__)
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _same_origin_header_matches_host(value: str, host: str | None) -> bool:
    if not value or not host:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return parsed.netloc.lower() == host.lower()


class LocalMutationSafetyMiddleware:
    """Reject browser-triggered cross-origin mutating HTTP requests."""

    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "").upper()
        if method not in _UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = headers.get("host")
        origin = headers.get("origin")
        referer = headers.get("referer")
        if origin is not None:
            allowed = _same_origin_header_matches_host(origin, host)
        elif referer is not None:
            allowed = _same_origin_header_matches_host(referer, host)
        else:
            allowed = True
        if allowed:
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            {"detail": "Mutating local API requests must be same-origin."},
            status_code=403,
        )
        await response(scope, receive, send)


def _failure_kind_for_request_error(exc: BaseException) -> str:
    if isinstance(exc, OperationalError):
        return "operational"
    if isinstance(exc, VibeSensorError):
        return "domain"
    return "programmer"


def _log_request_failure(
    *,
    exc: BaseException,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
) -> None:
    extra = log_extra(
        event="http_request_failed",
        failure_kind=_failure_kind_for_request_error(exc),
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
    )
    if isinstance(exc, OperationalError):
        LOGGER.warning("http_request_failed", extra=extra)
        return
    LOGGER.exception("http_request_failed", extra=extra)


class RequestLoggingMiddleware:
    """ASGI middleware that logs requests and preserves cancellation semantics."""

    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id, token = bind_request_id(headers.get(REQUEST_ID_HEADER))
        scope_state = scope.setdefault("state", {})
        if isinstance(scope_state, dict):
            scope_state["request_id"] = request_id

        started_at = perf_counter()
        status_code = 500
        request_completed = False
        response_started = False
        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")

        async def _send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                resolved_request_id = request_id or current_request_id()
                if resolved_request_id is not None:
                    MutableHeaders(scope=message)[REQUEST_ID_HEADER] = resolved_request_id
            await send(message)

        with start_span(
            __name__,
            "http.request",
            kind=SpanKind.SERVER,
            attributes={
                "http.method": method,
                "url.path": path,
                "vibesensor.request_id": request_id or "",
            },
        ) as span:
            try:
                await self.app(scope, receive, _send_with_request_id)
                request_completed = True
            except asyncio.CancelledError:
                span.set_attribute("vibesensor.cancelled", True)
                raise
            finally:
                duration_ms = round((perf_counter() - started_at) * 1000.0, 3)
                active_error = sys.exc_info()[1]
                span.set_attribute("http.status_code", status_code)
                span.set_attribute("vibesensor.duration_ms", duration_ms)
                span.set_attribute("vibesensor.response_started", response_started)
                if active_error is None and request_completed:
                    LOGGER.info(
                        "http_request",
                        extra=log_extra(
                            event="http_request",
                            method=method,
                            path=path,
                            status_code=status_code,
                            duration_ms=duration_ms,
                        ),
                    )
                elif active_error is not None:
                    mark_span_error(span, active_error)
                    _log_request_failure(
                        exc=active_error,
                        method=method,
                        path=path,
                        status_code=status_code,
                        duration_ms=duration_ms,
                    )
                reset_request_id(token)


def install_request_logging_middleware(app: FastAPI) -> None:
    app.add_middleware(RequestLoggingMiddleware)


def install_local_mutation_safety_middleware(app: FastAPI) -> None:
    app.add_middleware(LocalMutationSafetyMiddleware)
