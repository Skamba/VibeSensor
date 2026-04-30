"""Focused adversarial coverage for WebSocket ingress and broadcast pressure."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import anyio
import pytest
from test_support.ws_hub import make_websocket as _make_ws
from test_support.ws_hub import sent_json_sequence as _sent_json_sequence

from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.adapters.websocket.tick_controller import BroadcastTickController


@pytest.mark.asyncio
async def test_broadcast_evicts_slow_consumer_without_blocking_fast_clients() -> None:
    hub = WebSocketHub()
    fast_ws = _make_ws()
    slow_ws = _make_ws()

    async def _hang_forever(_payload: str) -> None:
        await anyio.sleep_forever()

    slow_ws.send_text.side_effect = _hang_forever
    await hub.add(fast_ws, None)
    await hub.add(slow_ws, None)
    hub._runner._send_timeout_s = 0.01

    await hub.broadcast(lambda _selected: {"ok": True})

    assert _sent_json_sequence(fast_ws) == [{"ok": True}]
    assert _sent_json_sequence(slow_ws) == [{"ok": True}]
    slow_ws.close.assert_awaited_once()
    assert hub.connection_count() == 1


@pytest.mark.asyncio
async def test_broadcast_pressure_builds_one_payload_per_unique_selection() -> None:
    hub = WebSocketHub()
    websockets = []
    selections = [None, "sensor-a", "sensor-b"]

    for index in range(48):
        ws = _make_ws()
        await hub.add(ws, selections[index % len(selections)])
        websockets.append(ws)

    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})

    await hub.broadcast(payload_builder)

    assert payload_builder.call_count == len(selections)
    for index, ws in enumerate(websockets):
        assert _sent_json_sequence(ws) == [{"selected": selections[index % len(selections)]}]


@pytest.mark.asyncio
async def test_broadcast_bounds_concurrent_sends_under_many_clients() -> None:
    hub = WebSocketHub()
    websockets = []
    active = 0
    max_active = 0

    async def _slow_send(_payload: str) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await anyio.sleep(0.01)
        active -= 1

    for index in range(8):
        ws = _make_ws()
        ws.send_text.side_effect = _slow_send
        await hub.add(ws, f"sensor-{index}")
        websockets.append(ws)
    hub._runner._max_concurrent_sends = 2
    hub._runner._max_sends_per_tick = len(websockets)

    await hub.broadcast(lambda selected: {"selected": selected})

    assert max_active == 2
    assert all(ws.send_text.await_count == 1 for ws in websockets)


@pytest.mark.asyncio
async def test_broadcast_skips_sends_over_tick_budget(caplog) -> None:
    hub = WebSocketHub()
    websockets = []
    for index in range(5):
        ws = _make_ws()
        await hub.add(ws, f"sensor-{index}")
        websockets.append(ws)
    hub._runner._max_sends_per_tick = 2

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda selected: {"selected": selected})

    assert [_sent_json_sequence(ws) for ws in websockets] == [
        [{"selected": "sensor-0"}],
        [{"selected": "sensor-1"}],
        [],
        [],
        [],
    ]
    assert hub.connection_count() == 5
    backpressure_logs = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "ws_broadcast_backpressure"
    ]
    assert len(backpressure_logs) == 1
    assert backpressure_logs[0].skipped_send_count == 3
    assert backpressure_logs[0].payload_cache_bytes > 0
    assert backpressure_logs[0].payload_serialization_count == 2
    assert backpressure_logs[0].tick_duration_ms >= 0


@pytest.mark.asyncio
async def test_tick_controller_skips_negative_sleep_when_broadcast_lags() -> None:
    controller = BroadcastTickController(
        hz=100,
        logger=logging.getLogger("vibesensor.adapters.websocket.hub"),
    )
    sleep_calls: list[float] = []

    async def _broadcast_tick() -> None:
        return None

    async def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        raise asyncio.CancelledError

    with (
        patch(
            "vibesensor.adapters.websocket.tick_controller.anyio.current_time",
            side_effect=[0.0, 0.05],
        ),
        patch(
            "vibesensor.adapters.websocket.tick_controller.anyio.sleep",
            side_effect=_fake_sleep,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await controller.run(broadcast_tick=_broadcast_tick)

    assert sleep_calls == [0.0]
