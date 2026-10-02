"""Adversarial client-message coverage for WebSocket routing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.http.ws_message_router import route_ws_message


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
def test_route_ws_message_ignores_invalid_messages(message: str) -> None:
    broadcaster = MagicMock()
    ws = MagicMock()

    route_ws_message(broadcaster, ws, message)

    broadcaster.select.assert_not_called()


def test_route_ws_message_applies_valid_selection() -> None:
    broadcaster = MagicMock()
    ws = MagicMock()

    route_ws_message(broadcaster, ws, json.dumps({"client_id": "AA:BB:CC:DD:EE:FF"}))

    broadcaster.select.assert_called_once_with(ws, "aabbccddeeff")


def test_route_ws_message_clears_selection_when_client_id_is_null() -> None:
    broadcaster = MagicMock()
    ws = MagicMock()

    route_ws_message(broadcaster, ws, json.dumps({"client_id": None}))

    broadcaster.select.assert_called_once_with(ws, None)
