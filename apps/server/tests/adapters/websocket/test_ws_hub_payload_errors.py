"""WebSocket hub payload-build failure behavior."""

from __future__ import annotations

import logging

import pytest
from test_support.ws_hub import build_hub
from test_support.ws_hub import make_websocket as _make_ws
from test_support.ws_hub import sent_json as _sent_json
from test_support.ws_hub import sent_json_sequence as _sent_json_sequence

from vibesensor.adapters.websocket.hub import WebSocketHub


@pytest.mark.asyncio
async def test_broadcast_survives_payload_builder_exception() -> None:
    hub, [ws] = await build_hub("client_a")

    def failing_builder(_client_id: str | None) -> dict[str, object]:
        raise RuntimeError("Payload build error")

    await hub.broadcast(failing_builder)

    assert hub.connection_count() == 1
    assert _sent_json_sequence(ws) == [{"error": "payload_build_failed"}]


@pytest.mark.asyncio
async def test_payload_error_does_not_block_other_clients() -> None:
    hub, [good_ws, bad_ws] = await build_hub("good_client", "bad_client")

    def selective_builder(client_id: str | None) -> dict[str, object]:
        if client_id == "bad_client":
            raise ValueError("cannot build for bad_client")
        return {"status": "ok", "client": client_id}

    await hub.broadcast(selective_builder)

    assert _sent_json_sequence(good_ws) == [{"status": "ok", "client": "good_client"}]
    assert _sent_json_sequence(bad_ws) == [{"error": "payload_build_failed"}]
    assert hub.connection_count() == 2


@pytest.mark.asyncio
async def test_payload_error_affected_count_uses_updated_selection(
    caplog: pytest.LogCaptureFixture,
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

    def selective_builder(client_id: str | None) -> dict[str, object]:
        if client_id == "client_b":
            raise RuntimeError("cannot build for client_b")
        return {"selected": client_id}

    with caplog.at_level(logging.ERROR, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(selective_builder)

    assert _sent_json(ws) == {"error": "payload_build_failed"}
    assert any("1 connection(s)" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_payload_error_logged_with_client_id_and_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hub, [ws] = await build_hub("sensor_42")

    with caplog.at_level(logging.ERROR, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda _cid: (_ for _ in ()).throw(RuntimeError("boom")))

    error_records = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("sensor_42" in record.message for record in error_records)
    assert any("1 connection(s)" in record.message for record in error_records)
    client_error = next(
        record
        for record in error_records
        if getattr(record, "selected_client_id", None) == "sensor_42"
    )
    assert client_error.event == "ws_payload_build_failed"


@pytest.mark.asyncio
async def test_payload_error_summary_counts_shared_failing_selection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hub, [ws1, ws2, ws3] = await build_hub("bad", "bad", "good")

    def builder(client_id: str | None) -> dict[str, object]:
        if client_id == "bad":
            raise RuntimeError("nope")
        return {"ok": True}

    with caplog.at_level(logging.ERROR, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(builder)

    assert _sent_json(ws3) == {"ok": True}
    assert _sent_json(ws1) == {"error": "payload_build_failed"}
    assert _sent_json(ws2) == {"error": "payload_build_failed"}
    summary_record = next(
        record
        for record in caplog.records
        if "WebSocket payload build failed for 1 client id(s) ('bad')" in record.message
    )
    assert summary_record.event == "ws_broadcast_payload_build_failed"
    assert summary_record.failed_client_ids == ["bad"]
    assert summary_record.affected_connection_count == 2
