"""Tests for the WebSocket broadcast hub."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from test_support.ws_hub import (
    build_hub,
)
from test_support.ws_hub import (
    make_websocket as _make_ws,
)
from test_support.ws_hub import (
    sent_json as _sent_json,
)

from vibesensor.adapters.websocket.hub import WebSocketHub, WSConnection
from vibesensor.shared.json_utils import sanitize_for_json


@pytest.mark.asyncio
async def test_add_remove() -> None:
    hub, [ws] = await build_hub(None)
    conns = await hub._snapshot()
    assert len(conns) == 1
    assert conns[0].websocket is ws
    await hub.remove(ws)
    assert await hub._snapshot() == []


@pytest.mark.asyncio
async def test_update_selected_client() -> None:
    hub, [ws] = await build_hub(None)
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
    hub, [ws] = await build_hub("client_a")
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
    hub, [ws1, ws2, ws3] = await build_hub("same", "same", None)
    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})

    await hub.broadcast(payload_builder)

    assert payload_builder.call_count == 2


@pytest.mark.asyncio
async def test_payload_error_does_not_block_other_clients() -> None:
    """A payload build failure for one client_id must not prevent other clients
    from receiving their data.
    """
    hub, [good_ws, bad_ws] = await build_hub("good_client", "bad_client")

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
async def test_broadcast_uses_latest_selection_when_selection_changes_during_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "client_a")
    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})
    selection_swapped = False

    async def fake_to_thread(func, /, *args, **kwargs):
        nonlocal selection_swapped
        if not selection_swapped:
            selection_swapped = True
            await hub.update_selected_client(ws, "client_b")
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "vibesensor.adapters.websocket.payload_orchestrator.anyio.to_thread.run_sync",
        fake_to_thread,
    )

    await hub.broadcast(payload_builder)

    assert _sent_json(ws) == {"selected": "client_b"}
    assert [call.args[0] for call in payload_builder.call_args_list] == [
        "client_a",
        "client_b",
    ]


@pytest.mark.asyncio
async def test_broadcast_reuses_lazy_payload_for_connections_converging_on_same_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()
    await hub.add(ws1, "client_a")
    await hub.add(ws2, "client_c")
    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})
    selection_swapped = False

    async def fake_to_thread(func, /, *args, **kwargs):
        nonlocal selection_swapped
        if not selection_swapped:
            selection_swapped = True
            await hub.update_selected_client(ws1, "client_b")
            await hub.update_selected_client(ws2, "client_b")
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "vibesensor.adapters.websocket.payload_orchestrator.anyio.to_thread.run_sync",
        fake_to_thread,
    )

    await hub.broadcast(payload_builder)

    assert _sent_json(ws1) == {"selected": "client_b"}
    assert _sent_json(ws2) == {"selected": "client_b"}
    assert [call.args[0] for call in payload_builder.call_args_list] == [
        "client_a",
        "client_c",
        "client_b",
    ]


@pytest.mark.asyncio
async def test_payload_error_affected_count_uses_updated_selection(
    caplog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "client_a")
    selection_swapped = False

    async def fake_to_thread(func, /, *args, **kwargs):
        nonlocal selection_swapped
        if not selection_swapped:
            selection_swapped = True
            await hub.update_selected_client(ws, "client_b")
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "vibesensor.adapters.websocket.payload_orchestrator.anyio.to_thread.run_sync",
        fake_to_thread,
    )

    def selective_builder(client_id):
        if client_id == "client_b":
            raise RuntimeError("cannot build for client_b")
        return {"selected": client_id}

    with caplog.at_level(logging.ERROR, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(selective_builder)

    assert _sent_json(ws) == {"error": "payload_build_failed"}
    assert any("1 connection(s)" in record.message for record in caplog.records)


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
    client_error = next(
        record
        for record in error_records
        if getattr(record, "selected_client_id", None) == "sensor_42"
    )
    assert client_error.event == "ws_payload_build_failed"


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
    summary_record = next(
        record
        for record in caplog.records
        if "WebSocket payload build failed for 1 client id(s) ('bad')" in record.message
    )
    assert summary_record.event == "ws_broadcast_payload_build_failed"
    assert summary_record.failed_client_ids == ["bad"]
    assert summary_record.affected_connection_count == 2


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


@pytest.mark.asyncio
async def test_broadcast_serializes_plain_payload_without_recursive_sanitizing() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, None)

    with patch(
        "vibesensor.adapters.websocket.payload_orchestrator.sanitize_for_json",
        side_effect=AssertionError(
            "sanitize_for_json should not run on the common plain-Python path"
        ),
    ):
        await hub.broadcast(lambda _: {"value": 1.5, "nested": {"ok": True}})

    assert _sent_json(ws) == {"value": 1.5, "nested": {"ok": True}}


@pytest.mark.asyncio
async def test_broadcast_offloads_serialization_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()
    await hub.add(ws1, "same")
    await hub.add(ws2, None)
    seen_selected_ids: list[str | None] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        seen_selected_ids.append(args[0])
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "vibesensor.adapters.websocket.payload_orchestrator.anyio.to_thread.run_sync",
        fake_to_thread,
    )

    await hub.broadcast(lambda selected: {"selected": selected})

    assert seen_selected_ids == ["same", None]
    assert _sent_json(ws1) == {"selected": "same"}
    assert _sent_json(ws2) == {"selected": None}


@pytest.mark.asyncio
async def test_broadcast_falls_back_to_sanitizer_for_numpy_payload() -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "client_x")
    payload = {"freq": np.array([1.0, float("nan"), 3.0], dtype=np.float32)}

    with patch(
        "vibesensor.adapters.websocket.payload_orchestrator.sanitize_for_json",
        wraps=sanitize_for_json,
    ) as sanitize:
        await hub.broadcast(lambda _: payload)

    assert sanitize.call_count == 1
    assert _sent_json(ws) == {"freq": [1.0, None, 3.0]}


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
    def test_empty_structures(self, empty: object) -> None:
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
    hub, [ws] = await build_hub("client_x")

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
    hub, [ws] = await build_hub("sensor_1")

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda _: {"val": float("nan")})

    assert any("NaN/Inf" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_broadcast_send_timeout_removes_connection() -> None:
    hub, [ws] = await build_hub("client-timeout")
    ws.send_text = AsyncMock(side_effect=TimeoutError("slow client"))

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

    with (
        patch(
            "vibesensor.adapters.websocket.broadcast_runner.anyio.current_time",
            side_effect=[1000.0, 1001.0],
        ),
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
    hub, [ws] = await build_hub("c1")
    ws.send_text = AsyncMock(side_effect=ConnectionError("gone"))
    ws.close = AsyncMock()

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
    hub, [ws] = await build_hub("sensor_42")
    ws.send_text = AsyncMock(side_effect=ConnectionError("boom"))

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda _: {"ok": True})

    warn_logs = [r for r in caplog.records if "broadcast send failed" in r.message]
    assert len(warn_logs) == 1
    assert "sensor_42" in warn_logs[0].message
    assert warn_logs[0].event == "ws_broadcast_send_failed"
    assert warn_logs[0].selected_client_id == "sensor_42"


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
