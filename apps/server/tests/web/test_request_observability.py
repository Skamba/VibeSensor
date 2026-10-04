from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from vibesensor.common.operational_errors import ServiceUnavailableError
from vibesensor.common.structured_logging import REQUEST_ID_HEADER, log_extra
from vibesensor.web.error_boundary import install_http_exception_handlers
from vibesensor.web.middleware import _request_log_level, install_request_logging_middleware
from vibesensor.web.settings.preferences import create_ui_preferences_routes


def _log_record(caplog: pytest.LogCaptureFixture, message: str):
    return next(rec for rec in caplog.records if rec.message == message)


def _audited_ui_preferences() -> SimpleNamespace:
    prefs = SimpleNamespace(language="en", speed_unit="kmh")
    logger = logging.getLogger("vibesensor.tests.request_observability")

    def _set_language(value: str) -> str:
        before = prefs.language
        prefs.language = value
        logger.info(
            "settings_change",
            extra=log_extra(
                settings_action="set_language",
                before=before,
                after=value,
            ),
        )
        return value

    prefs.set_language = _set_language
    prefs.set_speed_unit = MagicMock(return_value="kmh")
    return prefs


def test_request_logging_middleware_sets_response_header_and_logs_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    with caplog.at_level(logging.DEBUG, logger="vibesensor.web.middleware"):
        with TestClient(app) as client:
            response = client.get("/ping")

    assert response.status_code == 200
    request_log = _log_record(caplog, "http_request")
    assert response.headers[REQUEST_ID_HEADER] == request_log.request_id
    assert request_log.method == "GET"
    assert request_log.path == "/ping"
    assert request_log.status_code == 200
    # Routine fast reads (UI polling, phone connectivity probes) stay out of the info log.
    assert request_log.levelno == logging.DEBUG


@pytest.mark.parametrize(
    ("method", "status_code", "duration_ms", "level"),
    [
        pytest.param("GET", 200, 5.0, logging.DEBUG, id="fast-read"),
        pytest.param("GET", 302, 1.0, logging.DEBUG, id="probe-redirect"),
        pytest.param("GET", 200, 1500.0, logging.INFO, id="slow-read"),
        pytest.param("GET", 404, 1.0, logging.INFO, id="client-error"),
        pytest.param("GET", 503, 1.0, logging.INFO, id="server-error"),
        pytest.param("PUT", 200, 1.0, logging.INFO, id="mutation"),
        pytest.param("DELETE", 204, 1.0, logging.INFO, id="delete"),
    ],
)
def test_request_log_level_keeps_mutations_errors_and_slow_requests(
    method: str, status_code: int, duration_ms: float, level: int
) -> None:
    assert _request_log_level(method, status_code, duration_ms) == level


def test_request_id_flows_into_settings_audit_logs(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)
    app.include_router(create_ui_preferences_routes(_audited_ui_preferences()))

    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.put(
                "/api/settings/language",
                json={"language": "nl"},
                headers={REQUEST_ID_HEADER: "client-req-42"},
            )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "client-req-42"

    request_log = _log_record(caplog, "http_request")
    audit_log = next(
        rec
        for rec in caplog.records
        if rec.message == "settings_change"
        and getattr(rec, "settings_action", None) == "set_language"
    )
    assert request_log.request_id == "client-req-42"
    assert audit_log.request_id == "client-req-42"
    assert audit_log.before == "en"
    assert audit_log.after == "nl"


def test_unhandled_errors_keep_request_id_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)

    @app.get("/boom")
    async def boom() -> dict[str, bool]:
        raise ValueError("boom")

    with caplog.at_level(logging.INFO):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom", headers={REQUEST_ID_HEADER: "failing-request"})

    assert response.status_code == 500
    assert response.headers.get(REQUEST_ID_HEADER) is None
    failure_log = _log_record(caplog, "http_request_failed")
    assert failure_log.request_id == "failing-request"
    assert failure_log.failure_kind == "programmer"


class _Payload(BaseModel):
    value: int


def _handled_error_app() -> FastAPI:
    app = FastAPI()
    install_http_exception_handlers(app)
    install_request_logging_middleware(app)

    @app.get("/dependency-down")
    async def dependency_down() -> dict[str, bool]:
        raise ServiceUnavailableError("helper unavailable")

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail="teapot")

    @app.post("/items")
    async def create_item(payload: _Payload) -> dict[str, int]:
        return {"value": payload.value}

    return app


@pytest.mark.parametrize(
    ("method", "path", "body", "status_code", "detail"),
    [
        pytest.param(
            "GET", "/dependency-down", None, 503, "helper unavailable", id="operational-error"
        ),
        pytest.param("GET", "/teapot", None, 418, "teapot", id="http-exception"),
        pytest.param("POST", "/items", {"value": "bad"}, 422, None, id="request-validation"),
    ],
)
def test_handled_errors_keep_status_code_and_request_id(
    caplog: pytest.LogCaptureFixture,
    method: str,
    path: str,
    body: dict[str, object] | None,
    status_code: int,
    detail: str | None,
) -> None:
    with caplog.at_level(logging.INFO):
        with TestClient(_handled_error_app(), raise_server_exceptions=False) as client:
            response = client.request(
                method, path, json=body, headers={REQUEST_ID_HEADER: "handled-request"}
            )

    assert response.status_code == status_code
    if detail is not None:
        assert response.json() == {"detail": detail}
    assert response.headers[REQUEST_ID_HEADER] == "handled-request"
    request_log = _log_record(caplog, "http_request")
    assert request_log.request_id == "handled-request"
    assert request_log.status_code == status_code
    assert all(rec.message != "http_request_failed" for rec in caplog.records)
