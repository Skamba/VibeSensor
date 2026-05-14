"""WebSocket hub send-failure cleanup and logging behavior."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from test_support.ws_hub import build_hub
from test_support.ws_hub import make_websocket as _make_ws

from vibesensor.adapters.websocket.hub import WebSocketHub


@pytest.mark.asyncio
async def test_broadcast_send_timeout_removes_connection() -> None:
    hub, [ws] = await build_hub("client-timeout")
    ws.send_text = AsyncMock(side_effect=TimeoutError("slow client"))

    await hub.broadcast(lambda _: {"ok": True})

    assert hub.connection_count() == 0


@pytest.mark.asyncio
async def test_send_error_logging_is_rate_limited(
    caplog: pytest.LogCaptureFixture,
) -> None:
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

    send_fail_logs = [
        record for record in caplog.records if "broadcast send failed" in record.message
    ]
    assert len(send_fail_logs) == 1


@pytest.mark.asyncio
async def test_send_failure_log_includes_client_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hub, [ws] = await build_hub("sensor_42")
    ws.send_text = AsyncMock(side_effect=ConnectionError("boom"))

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda _: {"ok": True})

    warn_logs = [record for record in caplog.records if "broadcast send failed" in record.message]
    assert len(warn_logs) == 1
    assert "sensor_42" in warn_logs[0].message
    assert warn_logs[0].event == "ws_broadcast_send_failed"
    assert warn_logs[0].selected_client_id == "sensor_42"
