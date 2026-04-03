from __future__ import annotations

import asyncio
import concurrent.futures

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.adapters.http.middleware import install_request_logging_middleware
from vibesensor.shared.operational_errors import ServiceUnavailableError


def _app_with_endpoint(endpoint):
    app = FastAPI()
    install_request_logging_middleware(app)
    app.get("/")(endpoint)
    return app


def test_request_middleware_returns_500_for_application_exception() -> None:
    async def failing_endpoint() -> None:
        raise RuntimeError("boom")

    with TestClient(_app_with_endpoint(failing_endpoint), raise_server_exceptions=False) as client:
        response = client.get("/")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"


def test_request_middleware_reraises_cancelled_error() -> None:
    async def cancelled_endpoint() -> None:
        raise asyncio.CancelledError

    with TestClient(_app_with_endpoint(cancelled_endpoint)) as client:
        with pytest.raises((asyncio.CancelledError, concurrent.futures.CancelledError)):
            client.get("/")


def test_request_middleware_lets_programming_errors_propagate() -> None:
    async def failing_endpoint() -> None:
        raise TypeError("bad application state")

    with TestClient(_app_with_endpoint(failing_endpoint)) as client:
        with pytest.raises(TypeError, match="bad application state"):
            client.get("/")


def test_request_middleware_maps_operational_errors_to_503() -> None:
    async def failing_endpoint() -> None:
        raise ServiceUnavailableError("dependency unavailable")

    with TestClient(_app_with_endpoint(failing_endpoint), raise_server_exceptions=False) as client:
        response = client.get("/")

    assert response.status_code == 503
    assert response.json() == {"detail": "dependency unavailable"}
