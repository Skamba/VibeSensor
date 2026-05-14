"""WebSocket hub serialization and sanitizer fallback behavior."""

from __future__ import annotations

import logging
from unittest.mock import patch

import numpy as np
import pytest
from test_support.ws_hub import build_hub
from test_support.ws_hub import make_websocket as _make_ws
from test_support.ws_hub import sent_json as _sent_json
from test_support.ws_hub import sent_json_sequence as _sent_json_sequence

from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.shared.json_utils import sanitize_for_json


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
async def test_broadcast_falls_back_to_sanitizer_for_numpy_payload() -> None:
    hub, [ws] = await build_hub("client_x")
    payload = {"freq": np.array([1.0, float("nan"), 3.0], dtype=np.float32)}

    with patch(
        "vibesensor.adapters.websocket.payload_orchestrator.sanitize_for_json",
        wraps=sanitize_for_json,
    ) as sanitize:
        await hub.broadcast(lambda _: payload)

    assert sanitize.call_count == 1
    assert _sent_json(ws) == {"freq": [1.0, None, 3.0]}


@pytest.mark.asyncio
async def test_broadcast_sanitizes_nan_to_null() -> None:
    hub, [ws] = await build_hub("client_x")

    await hub.broadcast(
        lambda _: {
            "wheel": {"rpm": float("nan")},
            "speed": float("inf"),
            "ok": 42,
        }
    )

    parsed = _sent_json_sequence(ws)[0]
    assert parsed["wheel"]["rpm"] is None
    assert parsed["speed"] is None
    assert parsed["ok"] == 42


@pytest.mark.asyncio
async def test_broadcast_logs_warning_when_sanitizer_replaces_non_finite_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hub, [ws] = await build_hub("sensor_1")
    payload = {"freq": np.array([1.0, float("nan"), 3.0], dtype=np.float32)}

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"):
        await hub.broadcast(lambda _: payload)

    assert _sent_json(ws) == {"freq": [1.0, None, 3.0]}
    assert any("NaN/Inf" in record.message for record in caplog.records)
