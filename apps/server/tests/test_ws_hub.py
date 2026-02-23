"""Tests for the WebSocket broadcast hub."""

from __future__ import annotations

import json
import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.ws_hub import WebSocketHub, WSConnection, sanitize_for_json


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
    ws.send_text.assert_awaited_once()
    import json

    sent_text = ws.send_text.call_args[0][0]
    assert json.loads(sent_text) == {"data": "test"}


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
    bad_ws.send_text.side_effect = ConnectionError("gone")
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


@pytest.mark.asyncio
async def test_broadcast_survives_payload_builder_exception() -> None:
    """broadcast() should not crash when payload_builder raises."""
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "client_a")

    def failing_builder(client_id):
        raise RuntimeError("Payload build error")

    # Should not raise; the exception is caught inside _send
    await hub.broadcast(failing_builder)
    # Connection should NOT be removed (builder failed, not send)
    conns = await hub._snapshot()
    assert len(conns) == 1


@pytest.mark.asyncio
async def test_broadcast_builds_payload_once_per_unique_selection() -> None:
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()
    ws3 = _make_ws()
    await hub.add(ws1, "same")
    await hub.add(ws2, "same")
    await hub.add(ws3, None)
    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})

    await hub.broadcast(payload_builder)

    assert payload_builder.call_count == 2


# ── sanitize_for_json unit tests ─────────────────────────────────────────────


class TestSanitizeForJson:
    """Tests for the ``sanitize_for_json`` helper."""

    def test_nan_replaced_with_none(self) -> None:
        data = {"rpm": float("nan"), "ok": 42}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["rpm"] is None
        assert cleaned["ok"] == 42
        assert had is True

    def test_inf_replaced_with_none(self) -> None:
        data = {"val": float("inf")}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["val"] is None
        assert had is True

    def test_neg_inf_replaced_with_none(self) -> None:
        data = {"val": float("-inf")}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["val"] is None
        assert had is True

    def test_normal_floats_preserved(self) -> None:
        data = {"a": 1.5, "b": -3.14, "c": 0.0}
        cleaned, had = sanitize_for_json(data)
        assert cleaned == data
        assert had is False

    def test_nested_nan(self) -> None:
        data = {"outer": {"inner": [1.0, float("nan"), 3.0]}}
        cleaned, had = sanitize_for_json(data)
        assert cleaned == {"outer": {"inner": [1.0, None, 3.0]}}
        assert had is True

    def test_deeply_nested(self) -> None:
        data = {"a": [{"b": [float("inf"), {"c": float("-inf")}]}]}
        cleaned, had = sanitize_for_json(data)
        assert cleaned == {"a": [{"b": [None, {"c": None}]}]}
        assert had is True

    def test_non_float_types_untouched(self) -> None:
        data = {"s": "hello", "i": 42, "b": True, "n": None, "l": [1, 2]}
        cleaned, had = sanitize_for_json(data)
        assert cleaned == data
        assert had is False

    def test_empty_structures(self) -> None:
        cleaned, had = sanitize_for_json({})
        assert cleaned == {}
        assert had is False
        cleaned, had = sanitize_for_json([])
        assert cleaned == []
        assert had is False

    def test_output_is_valid_json(self) -> None:
        """Sanitised payload must round-trip through json.dumps(allow_nan=False)."""
        data = {
            "wheel": {"rpm": float("nan")},
            "spectrum": [float("inf"), 1.0, float("-inf")],
            "speed_mps": 25.5,
        }
        cleaned, had = sanitize_for_json(data)
        assert had is True
        text = json.dumps(cleaned, allow_nan=False)
        parsed = json.loads(text)
        assert parsed["wheel"]["rpm"] is None
        assert parsed["spectrum"] == [None, 1.0, None]
        assert parsed["speed_mps"] == 25.5

    def test_tuple_converted_to_list(self) -> None:
        data = {"t": (1.0, float("nan"), 3.0)}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["t"] == [1.0, None, 3.0]
        assert had is True


# ── Integration: broadcast with NaN sanitisation ─────────────────────────────


@pytest.mark.asyncio
async def test_broadcast_sanitizes_nan_to_null() -> None:
    """Broadcast with NaN values in payload produces valid JSON with null."""
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "client_x")

    payload_with_nan = {
        "wheel": {"rpm": float("nan")},
        "speed": float("inf"),
        "ok": 42,
    }
    await hub.broadcast(lambda _: payload_with_nan)

    ws.send_text.assert_awaited_once()
    sent = ws.send_text.call_args[0][0]
    parsed = json.loads(sent)  # Must not raise
    assert parsed["wheel"]["rpm"] is None
    assert parsed["speed"] is None
    assert parsed["ok"] == 42


@pytest.mark.asyncio
async def test_broadcast_logs_warning_on_nan(caplog) -> None:
    """A warning is logged when NaN/Inf values are found in the payload."""
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "sensor_1")

    import logging

    with caplog.at_level(logging.WARNING, logger="vibesensor.ws_hub"):
        await hub.broadcast(lambda _: {"val": float("nan")})

    assert any("NaN/Inf" in r.message for r in caplog.records)
