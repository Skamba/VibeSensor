from __future__ import annotations

import pytest

from vibesensor.adapters.simulator.scripted_speed_sync import (
    apply_scripted_speed,
    speed_sync_disable_message,
)


class _FakeSimClient:
    def __init__(self) -> None:
        self.current_speed_kmh = 0.0


@pytest.mark.asyncio
async def test_apply_scripted_speed_disables_sync_after_handled_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = [_FakeSimClient()]

    def fake_set_server_speed_override_kmh(
        host: str,
        port: int,
        speed_kmh: float,
        timeout_s: float,
    ) -> float:
        raise OSError("connection refused")

    monkeypatch.setattr(
        "vibesensor.adapters.simulator.scripted_speed_sync.set_server_speed_override_kmh",
        fake_set_server_speed_override_kmh,
    )

    result = await apply_scripted_speed(
        clients,
        42.0,
        server_host="127.0.0.1",
        server_http_port=8000,
        server_check_timeout=0.2,
        server_speed_sync_enabled=True,
    )

    assert clients[0].current_speed_kmh == 42.0
    assert result.server_speed_sync_enabled is False
    assert result.failure_message == speed_sync_disable_message(OSError("connection refused"))


@pytest.mark.asyncio
async def test_apply_scripted_speed_skips_http_call_when_sync_is_already_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = [_FakeSimClient()]
    called = False

    def fake_set_server_speed_override_kmh(
        host: str,
        port: int,
        speed_kmh: float,
        timeout_s: float,
    ) -> float:
        nonlocal called
        called = True
        return speed_kmh

    monkeypatch.setattr(
        "vibesensor.adapters.simulator.scripted_speed_sync.set_server_speed_override_kmh",
        fake_set_server_speed_override_kmh,
    )

    result = await apply_scripted_speed(
        clients,
        18.0,
        server_host="127.0.0.1",
        server_http_port=8000,
        server_check_timeout=0.2,
        server_speed_sync_enabled=False,
    )

    assert clients[0].current_speed_kmh == 18.0
    assert called is False
    assert result.server_speed_sync_enabled is False
    assert result.failure_message is None
