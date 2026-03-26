"""Simulator HTTP helper coverage for speed-override requests."""

from __future__ import annotations

import json
from urllib.request import Request

from vibesensor.adapters.simulator.server_http import set_server_speed_override_kmh


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_set_server_speed_override_uses_http_api_snake_case(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(req: Request, timeout: float) -> _FakeResponse:
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            {
                "speed_source": "manual",
                "manual_speed_kph": 55.0,
                "stale_timeout_s": 10.0,
            }
        )

    monkeypatch.setattr("vibesensor.adapters.simulator.server_http.urlopen", fake_urlopen)

    applied = set_server_speed_override_kmh("127.0.0.1", 8000, 55.0, 1.5)

    assert captured == {
        "url": "http://127.0.0.1:8000/api/settings/speed-source",
        "method": "PUT",
        "timeout": 1.5,
        "body": {"speed_source": "manual", "manual_speed_kph": 55.0},
    }
    assert applied == 55.0
