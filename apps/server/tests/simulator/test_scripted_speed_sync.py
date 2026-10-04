from __future__ import annotations

import pytest

from vibesensor.simulator.scripted_speed_sync import (
    apply_scripted_speed,
    speed_sync_failure_message,
)


class _FakeSimClient:
    def __init__(self) -> None:
        self.current_speed_kmh = 0.0


@pytest.mark.asyncio
async def test_apply_scripted_speed_reports_handled_http_error(
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
        "vibesensor.simulator.scripted_speed_sync.set_server_speed_override_kmh",
        fake_set_server_speed_override_kmh,
    )

    failure = await apply_scripted_speed(
        clients,
        42.0,
        server_host="127.0.0.1",
        server_http_port=8000,
        server_check_timeout=0.2,
        gps_feed=False,
    )

    assert clients[0].current_speed_kmh == 42.0
    assert failure == speed_sync_failure_message(OSError("connection refused"))


@pytest.mark.asyncio
@pytest.mark.parametrize(("gps_feed", "typed_in"), [(False, [18.0]), (True, [])])
async def test_apply_scripted_speed_types_it_in_unless_a_gps_feed_reports_it(
    monkeypatch: pytest.MonkeyPatch, gps_feed: bool, typed_in: list[float]
) -> None:
    clients = [_FakeSimClient()]
    pushed: list[float] = []

    def fake_set_server_speed_override_kmh(
        host: str,
        port: int,
        speed_kmh: float,
        timeout_s: float,
    ) -> float:
        pushed.append(speed_kmh)
        return speed_kmh

    monkeypatch.setattr(
        "vibesensor.simulator.scripted_speed_sync.set_server_speed_override_kmh",
        fake_set_server_speed_override_kmh,
    )

    failure = await apply_scripted_speed(
        clients,
        18.0,
        server_host="127.0.0.1",
        server_http_port=8000,
        server_check_timeout=0.2,
        gps_feed=gps_feed,
    )

    assert clients[0].current_speed_kmh == 18.0
    assert pushed == typed_in
    assert failure is None
