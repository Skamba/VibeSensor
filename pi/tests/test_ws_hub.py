"""Tests for the WebSocket broadcast hub."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.ws_hub import WebSocketHub, WSConnection


def _make_ws() -> AsyncMock:
    """Create a mock WebSocket with ``send_json``."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_add_remove() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, None)
    conns = await hub._snapshot()
    assert len(conns) == 1
    assert conns[0].websocket is ws
    await hub.remove(ws)
    assert await hub._snapshot() == []


@pytest.mark.asyncio
async def test_update_selected_client() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, None)
    await hub.update_selected_client(ws, "abc123")
    conns = await hub._snapshot()
    assert conns[0].selected_client_id == "abc123"


@pytest.mark.asyncio
async def test_update_selected_client_missing_ws() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    # Should not raise even though ws was never added
    await hub.update_selected_client(ws, "abc123")


@pytest.mark.asyncio
async def test_broadcast_calls_send_json() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "client_a")
    payload_builder = MagicMock(return_value={"data": "test"})
    await hub.broadcast(payload_builder)
    payload_builder.assert_called_once_with("client_a")
    ws.send_json.assert_awaited_once_with({"data": "test"})


@pytest.mark.asyncio
async def test_broadcast_no_connections() -> None:
    hub = WebSocketHub()
    payload_builder = MagicMock(return_value={})
    await hub.broadcast(payload_builder)
    payload_builder.assert_not_called()


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections() -> None:
    hub = WebSocketHub()
    good_ws = _make_ws()
    bad_ws = _make_ws()
    bad_ws.send_json.side_effect = ConnectionError("gone")
    await hub.add(good_ws, None)
    await hub.add(bad_ws, None)
    assert len(await hub._snapshot()) == 2
    await hub.broadcast(lambda _: {"ok": True})
    # bad_ws should have been removed
    conns = await hub._snapshot()
    assert len(conns) == 1
    assert conns[0].websocket is good_ws


@pytest.mark.asyncio
async def test_remove_nonexistent_is_noop() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    # Should not raise
    await hub.remove(ws)


@pytest.mark.asyncio
async def test_ws_connection_dataclass() -> None:
    ws = _make_ws()
    conn = WSConnection(websocket=ws, selected_client_id="test_id")
    assert conn.websocket is ws
    assert conn.selected_client_id == "test_id"
