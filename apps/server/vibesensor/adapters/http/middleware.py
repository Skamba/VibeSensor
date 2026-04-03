from __future__ import annotations

import asyncio
import logging
from time import perf_counter

from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vibesensor.adapters.http.error_boundary import http_exception_for_operational_error
from vibesensor.shared.operational_errors import OperationalError
from vibesensor.shared.structured_logging import (
    REQUEST_ID_HEADER,
    bind_request_id,
    current_request_id,
    log_extra,
    reset_request_id,
)

LOGGER = logging.getLogger(__name__)


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
        request_failed = False
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
        except asyncio.CancelledError:
            raise
        except OperationalError as exc:
            request_failed = True
            LOGGER.exception(
                "http_request_failed",
                extra=log_extra(
                    event="http_request_failed",
                    failure_kind="operational",
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round((perf_counter() - started_at) * 1000.0, 3),
                ),
            )
            if response_started:
                raise
            http_error = http_exception_for_operational_error(exc)
            operational_response = JSONResponse(
                status_code=http_error.status_code,
                content={"detail": http_error.detail},
            )
            await operational_response(scope, receive, _send_with_request_id)
        except Exception:
            request_failed = True
            LOGGER.exception(
                "http_request_failed",
                extra=log_extra(
                    event="http_request_failed",
                    failure_kind="programmer",
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round((perf_counter() - started_at) * 1000.0, 3),
                ),
            )
            if response_started:
                raise
            failure_response = PlainTextResponse("Internal Server Error", status_code=500)
            await failure_response(scope, receive, _send_with_request_id)
        finally:
            if not request_failed:
                LOGGER.info(
                    "http_request",
                    extra=log_extra(
                        event="http_request",
                        method=method,
                        path=path,
                        status_code=status_code,
                        duration_ms=round((perf_counter() - started_at) * 1000.0, 3),
                    ),
                )
            reset_request_id(token)


def install_request_logging_middleware(app: FastAPI) -> None:
    app.add_middleware(RequestLoggingMiddleware)
