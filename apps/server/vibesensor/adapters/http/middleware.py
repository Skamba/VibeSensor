from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import FastAPI, Request
from starlette.responses import PlainTextResponse, Response

from vibesensor.shared.structured_logging import (
    REQUEST_ID_HEADER,
    bind_request_id,
    current_request_id,
    log_extra,
    reset_request_id,
)

LOGGER = logging.getLogger(__name__)


def _attach_request_id(response: Response, request_id: str | None = None) -> Response:
    resolved_request_id = request_id or current_request_id()
    if resolved_request_id is not None:
        response.headers[REQUEST_ID_HEADER] = resolved_request_id
    return response


def install_request_logging_middleware(app: FastAPI) -> None:
    async def _request_logging_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id, token = bind_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        started_at = perf_counter()
        status_code = 500
        request_failed = False
        try:
            response = await call_next(request)
            status_code = response.status_code
            return _attach_request_id(response, request_id)
        except Exception:
            request_failed = True
            LOGGER.exception(
                "http_request_failed",
                extra=log_extra(
                    event="http_request_failed",
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    duration_ms=round((perf_counter() - started_at) * 1000.0, 3),
                ),
            )
            return _attach_request_id(
                PlainTextResponse("Internal Server Error", status_code=500),
                request_id,
            )
        finally:
            if not request_failed:
                LOGGER.info(
                    "http_request",
                    extra=log_extra(
                        event="http_request",
                        method=request.method,
                        path=request.url.path,
                        status_code=status_code,
                        duration_ms=round((perf_counter() - started_at) * 1000.0, 3),
                    ),
                )
            reset_request_id(token)

    app.middleware("http")(_request_logging_middleware)
