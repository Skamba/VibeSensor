from __future__ import annotations

import logging
import sys
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vibesensor.common.exceptions import VibeSensorError
from vibesensor.common.operational_errors import OperationalError
from vibesensor.common.structured_logging import (
    REQUEST_ID_HEADER,
    bind_request_id,
    current_request_id,
    log_extra,
    reset_request_id,
)
from vibesensor.hotspot.captive_portal import PORTAL_URL, is_probe_host

LOGGER = logging.getLogger(__name__)
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SLOW_REQUEST_MS = 1000.0
"""Successful reads slower than this are logged at info; faster ones at debug."""


def _request_log_level(method: str, status_code: int, duration_ms: float) -> int:
    """Info for mutations, errors and slow requests; debug for routine reads.

    The UI polls status endpoints every second or two and phones probe for
    connectivity every 30 s, so logging every read at info floods the journal.
    """
    if method in _UNSAFE_METHODS or status_code >= 400 or duration_ms >= _SLOW_REQUEST_MS:
        return logging.INFO
    return logging.DEBUG


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


class CaptivePortalMiddleware:
    """Redirect OS connectivity probes (resolved to the Pi by the hotspot DNS) to the UI."""

    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not is_probe_host(Headers(scope=scope).get("host")):
            await self.app(scope, receive, send)
            return
        response = RedirectResponse(
            PORTAL_URL,
            status_code=302,
            headers={"Cache-Control": "no-store"},
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
    """ASGI middleware that logs requests and preserves cancellation semantics.

    Every request gets an ``X-Request-ID``; see ``_request_log_level`` for which
    completed requests reach the info log.
    """

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

        try:
            await self.app(scope, receive, _send_with_request_id)
            request_completed = True
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000.0, 3)
            active_error = sys.exc_info()[1]
            if active_error is None and request_completed:
                LOGGER.log(
                    _request_log_level(method.upper(), status_code, duration_ms),
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


def install_captive_portal_middleware(app: FastAPI) -> None:
    app.add_middleware(CaptivePortalMiddleware)
