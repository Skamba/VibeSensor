"""Tests for the WebSocket broadcast hub."""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibesensor.adapters.websocket.hub import WebSocketHub, WSConnection
from vibesensor.shared.utils.json_utils import sanitize_for_json


def _make_ws() -> AsyncMock:
    """Create a mock WebSocket with ``send_text``."""
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def _sent_json(ws: AsyncMock) -> Any:
    """Return the parsed JSON sent via ``ws.send_text``."""
    return json.loads(ws.send_text.call_args[0][0])


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
    # Verify no connections were created as a side effect
    conns = await hub._snapshot()
    assert len(conns) == 0


@pytest.mark.asyncio
async def test_broadcast_calls_send_json() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "client_a")
    payload_builder = MagicMock(return_value={"data": "test"})
    await hub.broadcast(payload_builder)
    payload_builder.assert_called_once_with("client_a")
    ws.send_text.assert_awaited_once()
    assert _sent_json(ws) == {"data": "test"}


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
    # Verify hub is still empty
    conns = await hub._snapshot()
    assert len(conns) == 0


@pytest.mark.asyncio
async def test_ws_connection_dataclass() -> None:
    ws = _make_ws()
    conn = WSConnection(connection_id=1, websocket=ws, selected_client_id="test_id")
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

    # Should not raise; the exception is caught inside _build_payload
    await hub.broadcast(failing_builder)
    # Connection should NOT be removed (builder failed, not send)
    conns = await hub._snapshot()
    assert len(conns) == 1
    # Connection should receive the error payload instead of nothing
    ws.send_text.assert_awaited_once()
    assert _sent_json(ws) == {"error": "payload_build_failed"}


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


@pytest.mark.asyncio
async def test_payload_error_does_not_block_other_clients() -> None:
    """A payload build failure for one client_id must not prevent other clients
    from receiving their data.
    """
    hub = WebSocketHub()
    good_ws = _make_ws()
    bad_ws = _make_ws()
    await hub.add(good_ws, "good_client")
    await hub.add(bad_ws, "bad_client")

    def selective_builder(client_id):
        if client_id == "bad_client":
            raise ValueError("cannot build for bad_client")
        return {"status": "ok", "client": client_id}

    await hub.broadcast(selective_builder)

    # good_ws received normal payload
    good_ws.send_text.assert_awaited_once()
    assert _sent_json(good_ws) == {"status": "ok", "client": "good_client"}

    # bad_ws received error payload (not silently skipped)
    bad_ws.send_text.assert_awaited_once()
    assert _sent_json(bad_ws) == {"error": "payload_build_failed"}

    # Both connections are still alive
    conns = await hub._snapshot()
    assert len(conns) == 2


@pytest.mark.asyncio
async def test_payload_error_logged_at_error_level(caplog) -> None:
    """Payload build failures must be logged at ERROR level with client id."""
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "sensor_42")

    with caplog.at_level(logging.ERROR, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda _cid: (_ for _ in ()).throw(RuntimeError("boom")))

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1
    # Per-client error log should mention the client id
    assert any("sensor_42" in r.message for r in error_records)
    # Summary log should mention connection count
    assert any("1 connection(s)" in r.message for r in error_records)


@pytest.mark.asyncio
async def test_payload_error_affected_count_logged(caplog) -> None:
    """When multiple connections share a failing client_id the summary log
    reports the total affected count.
    """
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()
    ws3 = _make_ws()
    await hub.add(ws1, "bad")
    await hub.add(ws2, "bad")
    await hub.add(ws3, "good")

    def builder(cid):
        if cid == "bad":
            raise RuntimeError("nope")
        return {"ok": True}

    with caplog.at_level(logging.ERROR, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(builder)

    # ws3 (good) got normal payload
    assert _sent_json(ws3) == {"ok": True}

    # Both bad connections got error payload
    for ws in (ws1, ws2):
        assert _sent_json(ws) == {"error": "payload_build_failed"}

    # Summary log mentions 2 affected connections
    assert any("2 connection(s)" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_error_payload_is_cached_per_client_id() -> None:
    """The error payload should be cached so payload_builder is called only
    once per unique client_id, even on failure.
    """
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()
    await hub.add(ws1, "fail_client")
    await hub.add(ws2, "fail_client")

    call_count = 0

    def counting_builder(cid):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("always fails")

    await hub.broadcast(counting_builder)

    # Builder should only be called once (cached error payload for second conn)
    assert call_count == 1
    # Both connections still received the error payload
    for ws in (ws1, ws2):
        ws.send_text.assert_awaited_once()
        assert _sent_json(ws) == {"error": "payload_build_failed"}


# ── sanitize_for_json unit tests ─────────────────────────────────────────────


class TestSanitizeForJson:
    """Tests for the ``sanitize_for_json`` helper."""

    @pytest.mark.parametrize(
        ("label", "value"),
        [("nan", float("nan")), ("inf", float("inf")), ("-inf", float("-inf"))],
        ids=["nan", "inf", "neg_inf"],
    )
    def test_non_finite_replaced_with_none(self, label: str, value: float) -> None:
        data = {"val": value, "ok": 42}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["val"] is None
        assert cleaned["ok"] == 42
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

    @pytest.mark.parametrize("empty", [{}, []], ids=["dict", "list"])
    def test_empty_structures(self, empty: Any) -> None:
        cleaned, had = sanitize_for_json(empty)
        assert cleaned == empty
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

    def test_numpy_scalars_converted(self) -> None:
        import numpy as np

        data = {"a": np.float32(1.5), "b": np.int64(42), "c": np.float64(float("nan"))}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["a"] == 1.5
        assert isinstance(cleaned["a"], float)
        assert cleaned["b"] == 42
        assert isinstance(cleaned["b"], int)
        assert cleaned["c"] is None
        assert had is True

    def test_numpy_arrays_converted(self) -> None:
        import numpy as np

        data = {"arr": np.array([1.0, float("nan"), 3.0])}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["arr"] == [1.0, None, 3.0]
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
    parsed = _sent_json(ws)
    assert parsed["wheel"]["rpm"] is None
    assert parsed["speed"] is None
    assert parsed["ok"] == 42


@pytest.mark.asyncio
async def test_broadcast_logs_warning_on_nan(caplog) -> None:
    """A warning is logged when NaN/Inf values are found in the payload."""
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "sensor_1")

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda _: {"val": float("nan")})

    assert any("NaN/Inf" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_broadcast_send_timeout_removes_connection() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    ws.send_text = AsyncMock(side_effect=TimeoutError("slow client"))
    await hub.add(ws, "client-timeout")

    await hub.broadcast(lambda _: {"ok": True})

    assert await hub._snapshot() == []


@pytest.mark.asyncio
async def test_send_error_logging_is_rate_limited(caplog) -> None:
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()
    ws1.send_text = AsyncMock(side_effect=ConnectionError("boom-1"))
    ws2.send_text = AsyncMock(side_effect=ConnectionError("boom-2"))
    await hub.add(ws1, "c1")
    await hub.add(ws2, "c2")

    fake_loop = MagicMock()
    fake_loop.time.side_effect = [1000.0, 1001.0]
    with (
        patch("vibesensor.adapters.websocket.hub.asyncio.get_running_loop", return_value=fake_loop),
        caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"),
    ):
        await hub.broadcast(lambda _: {"ok": True})

    send_fail_logs = [r for r in caplog.records if "broadcast send failed" in r.message]
    assert len(send_fail_logs) == 1


# ── connection_count() tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connection_count_empty() -> None:
    """connection_count() returns 0 when no connections are registered."""
    hub = WebSocketHub()
    assert hub.connection_count() == 0


@pytest.mark.asyncio
async def test_connection_count_tracks_add_remove() -> None:
    """connection_count() reflects add/remove operations correctly."""
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()
    assert hub.connection_count() == 0
    await hub.add(ws1, None)
    assert hub.connection_count() == 1
    await hub.add(ws2, "sensor_x")
    assert hub.connection_count() == 2
    await hub.remove(ws1)
    assert hub.connection_count() == 1
    await hub.remove(ws2)
    assert hub.connection_count() == 0


# ── graceful close of dead connections ───────────────────────────────────────


@pytest.mark.asyncio
async def test_broadcast_closes_dead_websocket() -> None:
    """broadcast() should call ws.close() on failed connections before removing."""
    hub = WebSocketHub()
    ws = _make_ws()
    ws.send_text = AsyncMock(side_effect=ConnectionError("gone"))
    ws.close = AsyncMock()
    await hub.add(ws, "c1")

    await hub.broadcast(lambda _: {"ok": True})

    ws.close.assert_awaited_once()
    assert await hub._snapshot() == []


@pytest.mark.asyncio
async def test_broadcast_close_error_does_not_prevent_removal() -> None:
    """Even if ws.close() raises, the connection must still be removed from hub."""
    hub = WebSocketHub()
    ws = _make_ws()
    ws.send_text = AsyncMock(side_effect=ConnectionError("gone"))
    ws.close = AsyncMock(side_effect=RuntimeError("already closed"))
    await hub.add(ws, None)

    await hub.broadcast(lambda _: {"data": True})

    # Hub should have cleaned up despite close() raising.
    assert await hub._snapshot() == []


# ── send-failure log includes selected_client_id ─────────────────────────────


@pytest.mark.asyncio
async def test_send_failure_log_includes_client_id(caplog) -> None:
    """The send-failure WARNING message must include the selected_client_id."""
    hub = WebSocketHub()
    ws = _make_ws()
    ws.send_text = AsyncMock(side_effect=ConnectionError("boom"))
    await hub.add(ws, "sensor_42")

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda _: {"ok": True})

    warn_logs = [r for r in caplog.records if "broadcast send failed" in r.message]
    assert len(warn_logs) == 1
    assert "sensor_42" in warn_logs[0].message


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
    assert await hub._snapshot() == []
