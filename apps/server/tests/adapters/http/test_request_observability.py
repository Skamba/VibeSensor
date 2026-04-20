from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.adapters.http.error_boundary import install_http_exception_handlers
from vibesensor.adapters.http.middleware import install_request_logging_middleware
from vibesensor.adapters.http.settings import create_settings_routes
from vibesensor.shared.operational_errors import ServiceUnavailableError
from vibesensor.shared.structured_logging import REQUEST_ID_HEADER, log_extra


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

    with caplog.at_level(logging.INFO, logger="vibesensor.adapters.http.middleware"):
        with TestClient(app) as client:
            response = client.get("/ping")

    assert response.status_code == 200
    request_log = _log_record(caplog, "http_request")
    assert response.headers[REQUEST_ID_HEADER] == request_log.request_id
    assert request_log.method == "GET"
    assert request_log.path == "/ping"
    assert request_log.status_code == 200


def test_request_id_flows_into_settings_audit_logs(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)
    app.include_router(
        create_settings_routes(
            MagicMock(),
            MagicMock(),
            _audited_ui_preferences(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
    )

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


def test_operational_errors_use_http_handlers_and_keep_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    install_http_exception_handlers(app)
    install_request_logging_middleware(app)

    @app.get("/dependency-down")
    async def dependency_down() -> dict[str, bool]:
        raise ServiceUnavailableError("helper unavailable")

    with caplog.at_level(logging.INFO):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/dependency-down",
                headers={REQUEST_ID_HEADER: "operational-request"},
            )

    assert response.status_code == 503
    assert response.json() == {"detail": "helper unavailable"}
    assert response.headers[REQUEST_ID_HEADER] == "operational-request"
    request_log = _log_record(caplog, "http_request")
    assert request_log.request_id == "operational-request"
    assert request_log.status_code == 503
    assert all(rec.message != "http_request_failed" for rec in caplog.records)


def test_http_exception_keeps_status_code_and_request_id(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail="teapot")

    with caplog.at_level(logging.INFO):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/teapot", headers={REQUEST_ID_HEADER: "teapot-request"})

    assert response.status_code == 418
    assert response.headers[REQUEST_ID_HEADER] == "teapot-request"
    request_log = _log_record(caplog, "http_request")
    assert request_log.request_id == "teapot-request"
    assert request_log.status_code == 418
    assert all(rec.message != "http_request_failed" for rec in caplog.records)


def test_request_validation_error_keeps_status_code_and_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)

    class Payload(BaseModel):
        value: int

    @app.post("/items")
    async def create_item(payload: Payload) -> dict[str, int]:
        return {"value": payload.value}

    with caplog.at_level(logging.INFO):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/items",
                json={"value": "bad"},
                headers={REQUEST_ID_HEADER: "validation-request"},
            )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "validation-request"
    request_log = _log_record(caplog, "http_request")
    assert request_log.request_id == "validation-request"
    assert request_log.status_code == 422
    assert all(rec.message != "http_request_failed" for rec in caplog.records)


def test_request_logging_middleware_exports_http_trace_span(tmp_path: Path) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    with configured_trace_output(tmp_path) as trace_path:
        with TestClient(app) as client:
            response = client.get("/ping", headers={REQUEST_ID_HEADER: "trace-request"})

    assert response.status_code == 200
    span = next(item for item in read_trace_output(trace_path) if item["name"] == "http.request")
    assert span["kind"] == "server"
    assert span["attributes"]["http.method"] == "GET"
    assert span["attributes"]["url.path"] == "/ping"
    assert span["attributes"]["http.status_code"] == 200
    assert span["attributes"]["vibesensor.request_id"] == "trace-request"
