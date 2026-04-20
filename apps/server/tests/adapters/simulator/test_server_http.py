"""Simulator HTTP helper coverage for health checks and speed overrides."""

from __future__ import annotations

import json

import httpx
import pytest
from pytest_httpx import HTTPXMock
from test_support.httpx import add_httpx_exception, add_json_response, add_text_response

from vibesensor.adapters.simulator.server_http import (
    check_server_running,
    set_server_speed_override_kmh,
)


def test_check_server_running_returns_true_on_200(httpx_mock: HTTPXMock) -> None:
    url = "http://127.0.0.1:8000/api/clients"
    add_text_response(httpx_mock, url=url, text="{}", headers={"Content-Type": "application/json"})

    assert check_server_running("127.0.0.1", 8000, timeout_s=0.5) is True


def test_check_server_running_returns_false_on_non_200(httpx_mock: HTTPXMock) -> None:
    url = "http://127.0.0.1:8000/api/clients"
    add_text_response(httpx_mock, url=url, text="booting", status_code=503)

    assert check_server_running("127.0.0.1", 8000, timeout_s=0.5) is False


def test_check_server_running_returns_false_on_timeout(httpx_mock: HTTPXMock) -> None:
    url = "http://127.0.0.1:8000/api/clients"
    add_httpx_exception(httpx_mock, url=url, exception=httpx.ReadTimeout("timed out"))

    assert check_server_running("127.0.0.1", 8000, timeout_s=0.5) is False


def test_check_server_running_returns_false_on_connection_failure(httpx_mock: HTTPXMock) -> None:
    url = "http://127.0.0.1:8000/api/clients"
    add_httpx_exception(httpx_mock, url=url, exception=httpx.ConnectError("connection refused"))

    assert check_server_running("127.0.0.1", 8000, timeout_s=0.5) is False


def test_set_server_speed_override_uses_http_api_snake_case(httpx_mock: HTTPXMock) -> None:
    url = "http://127.0.0.1:8000/api/settings/speed-source"
    add_json_response(
        httpx_mock,
        url=url,
        method="PUT",
        payload={
            "speed_source": "manual",
            "manual_speed_kph": 55.0,
            "stale_timeout_s": 10.0,
        },
    )

    applied = set_server_speed_override_kmh("127.0.0.1", 8000, 55.0, 1.5)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert {
        "url": str(requests[0].url),
        "method": requests[0].method,
        "content_type": requests[0].headers["Content-Type"],
        "body": json.loads(requests[0].content.decode("utf-8")),
    } == {
        "url": url,
        "method": "PUT",
        "content_type": "application/json",
        "body": {"speed_source": "manual", "manual_speed_kph": 55.0},
    }
    assert applied == 55.0


def test_set_server_speed_override_returns_none_for_malformed_response_payload(
    httpx_mock: HTTPXMock,
) -> None:
    url = "http://127.0.0.1:8000/api/settings/speed-source"
    add_json_response(
        httpx_mock,
        url=url,
        method="PUT",
        payload={"speed_source": "manual", "manual_speed_kph": "55.0"},
    )

    assert set_server_speed_override_kmh("127.0.0.1", 8000, 55.0, 1.5) is None


def test_set_server_speed_override_propagates_status_failures(httpx_mock: HTTPXMock) -> None:
    url = "http://127.0.0.1:8000/api/settings/speed-source"
    add_text_response(httpx_mock, url=url, text="busy", status_code=503, method="PUT")

    with pytest.raises(OSError, match="HTTP 503"):
        set_server_speed_override_kmh("127.0.0.1", 8000, 55.0, 1.5)


def test_set_server_speed_override_propagates_connection_failures(
    httpx_mock: HTTPXMock,
) -> None:
    url = "http://127.0.0.1:8000/api/settings/speed-source"
    add_httpx_exception(
        httpx_mock,
        url=url,
        method="PUT",
        exception=httpx.ConnectError("connection refused"),
    )

    with pytest.raises(OSError, match="connection refused"):
        set_server_speed_override_kmh("127.0.0.1", 8000, 55.0, 1.5)
