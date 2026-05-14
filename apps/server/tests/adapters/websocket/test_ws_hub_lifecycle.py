"""WebSocket hub connection lifecycle and cleanup behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from test_support.ws_hub import build_hub
from test_support.ws_hub import make_websocket as _make_ws
from test_support.ws_hub import sent_json_sequence as _sent_json_sequence

from vibesensor.adapters.websocket.hub import WebSocketHub


@pytest.mark.asyncio
async def test_add_remove_updates_connection_count() -> None:
    hub, [ws] = await build_hub(None)

    assert hub.connection_count() == 1
    await hub.remove(ws)

    assert hub.connection_count() == 0


@pytest.mark.asyncio
async def test_remove_unknown_connection_is_noop() -> None:
    hub = WebSocketHub()

    await hub.remove(_make_ws())

    assert hub.connection_count() == 0


@pytest.mark.asyncio
async def test_connection_count_tracks_multiple_connections() -> None:
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()

    await hub.add(ws1, None)
    await hub.add(ws2, "sensor_x")
    await hub.remove(ws1)

    assert hub.connection_count() == 1
    await hub.remove(ws2)
    assert hub.connection_count() == 0


@pytest.mark.asyncio
async def test_broadcast_removes_failed_connection_but_keeps_live_connection() -> None:
    hub = WebSocketHub()
    good_ws = _make_ws()
    bad_ws = _make_ws()
    bad_ws.send_text.side_effect = ConnectionError("gone")
    await hub.add(good_ws, None)
    await hub.add(bad_ws, None)

    await hub.broadcast(lambda _: {"ok": True})

    assert hub.connection_count() == 1
    assert _sent_json_sequence(good_ws) == [{"ok": True}]


@pytest.mark.asyncio
async def test_broadcast_closes_dead_websocket_before_removing() -> None:
    hub, [ws] = await build_hub("c1")
    ws.send_text = AsyncMock(side_effect=ConnectionError("gone"))
    ws.close = AsyncMock()

    await hub.broadcast(lambda _: {"ok": True})

    ws.close.assert_awaited_once()
    assert hub.connection_count() == 0


@pytest.mark.asyncio
async def test_close_error_does_not_prevent_failed_connection_removal() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    ws.send_text = AsyncMock(side_effect=ConnectionError("gone"))
    ws.close = AsyncMock(side_effect=RuntimeError("already closed"))
    await hub.add(ws, None)

    await hub.broadcast(lambda _: {"data": True})

    assert hub.connection_count() == 0


@pytest.mark.asyncio
async def test_broadcast_skips_cleanup_for_connection_removed_during_send() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    ws.close = AsyncMock()

    async def _remove_then_fail(_payload: str) -> None:
        await hub.remove(ws)
        raise ConnectionError("gone")

    ws.send_text = AsyncMock(side_effect=_remove_then_fail)
    await hub.add(ws, "client-racy")

    await hub.broadcast(lambda _: {"ok": True})

    ws.close.assert_not_awaited()
    assert hub.connection_count() == 0
