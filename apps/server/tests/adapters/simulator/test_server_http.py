"""Simulator HTTP helper coverage for health checks and speed overrides."""

from __future__ import annotations

import json

import pytest

from vibesensor.adapters.simulator.server_http import (
    check_server_running,
    set_server_speed_override_kmh,
)


def test_check_server_running_returns_true_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vibesensor.adapters.simulator.server_http.read_text_response",
        lambda url, *, timeout_s, context: (200, "application/json", "{}"),
    )

    assert check_server_running("127.0.0.1", 8000, timeout_s=0.5) is True


def test_check_server_running_returns_false_on_non_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibesensor.adapters.simulator.server_http.read_text_response",
        lambda url, *, timeout_s, context: (503, "text/plain", "booting"),
    )

    assert check_server_running("127.0.0.1", 8000, timeout_s=0.5) is False


def test_check_server_running_returns_false_on_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_text_response(url, *, timeout_s, context):
        raise OSError("connection refused")

    monkeypatch.setattr(
        "vibesensor.adapters.simulator.server_http.read_text_response",
        fake_read_text_response,
    )

    assert check_server_running("127.0.0.1", 8000, timeout_s=0.5) is False


def test_set_server_speed_override_uses_http_api_snake_case(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_read_json_response(
        url: str,
        *,
        method: str,
        headers: dict[str, str],
        content: bytes,
        timeout_s: float,
        context: str,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["method"] = method
        captured["timeout"] = timeout_s
        captured["context"] = context
        captured["body"] = json.loads(content.decode("utf-8"))
        return {
            "speed_source": "manual",
            "manual_speed_kph": 55.0,
            "stale_timeout_s": 10.0,
        }

    monkeypatch.setattr(
        "vibesensor.adapters.simulator.server_http.read_json_response",
        fake_read_json_response,
    )

    applied = set_server_speed_override_kmh("127.0.0.1", 8000, 55.0, 1.5)

    assert captured == {
        "url": "http://127.0.0.1:8000/api/settings/speed-source",
        "method": "PUT",
        "timeout": 1.5,
        "context": "simulator speed override",
        "body": {"speed_source": "manual", "manual_speed_kph": 55.0},
    }
    assert applied == 55.0


def test_set_server_speed_override_propagates_http_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_json_response(
        url: str,
        *,
        method: str,
        headers: dict[str, str],
        content: bytes,
        timeout_s: float,
        context: str,
    ) -> dict[str, object]:
        raise OSError("HTTP 503")

    monkeypatch.setattr(
        "vibesensor.adapters.simulator.server_http.read_json_response",
        fake_read_json_response,
    )

    with pytest.raises(OSError, match="HTTP 503"):
        set_server_speed_override_kmh("127.0.0.1", 8000, 55.0, 1.5)
