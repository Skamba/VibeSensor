from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.adapters.http.middleware import install_request_logging_middleware
from vibesensor.adapters.http.settings import create_settings_routes
from vibesensor.infra.config.settings_store import SettingsStore
from vibesensor.shared.structured_logging import REQUEST_ID_HEADER


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
    request_log = next(rec for rec in caplog.records if rec.message == "http_request")
    assert response.headers[REQUEST_ID_HEADER] == request_log.request_id
    assert request_log.method == "GET"
    assert request_log.path == "/ping"
    assert request_log.status_code == 200


def test_request_id_flows_into_settings_audit_logs(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)
    app.include_router(create_settings_routes(SettingsStore(), MagicMock()))

    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.put(
                "/api/settings/language",
                json={"language": "nl"},
                headers={REQUEST_ID_HEADER: "client-req-42"},
            )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "client-req-42"

    request_log = next(rec for rec in caplog.records if rec.message == "http_request")
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


def test_unhandled_errors_still_echo_request_id(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    install_request_logging_middleware(app)

    @app.get("/boom")
    async def boom() -> dict[str, bool]:
        raise ValueError("boom")

    with caplog.at_level(logging.INFO):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom", headers={REQUEST_ID_HEADER: "failing-request"})

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "failing-request"
    failure_log = next(rec for rec in caplog.records if rec.message == "http_request_failed")
    assert failure_log.request_id == "failing-request"
