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
