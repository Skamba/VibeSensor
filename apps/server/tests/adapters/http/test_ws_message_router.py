"""Adversarial client-message coverage for WebSocket routing."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from vibesensor.adapters.http.ws_message_router import route_ws_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "not-json",
        json.dumps(["unexpected-list"]),
        json.dumps({"unknown": "field"}),
        json.dumps({"client_id": "x" * 4096}),
        json.dumps({"client_id": ["bad-type"]}),
    ],
    ids=[
        "malformed-json",
        "non-dict-json",
        "unknown-keys",
        "oversized-client-id",
        "wrong-client-id-type",
    ],
)
async def test_route_ws_message_ignores_invalid_messages(message: str) -> None:
    hub = AsyncMock()
    ws = AsyncMock()

    await route_ws_message(hub, ws, message)

    hub.update_selected_client.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_ws_message_applies_valid_selection() -> None:
    hub = AsyncMock()
    ws = AsyncMock()

    await route_ws_message(hub, ws, json.dumps({"client_id": "AA:BB:CC:DD:EE:FF"}))

    hub.update_selected_client.assert_awaited_once_with(ws, "aabbccddeeff")
