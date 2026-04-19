"""Shared builders for WebSocket hub tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from vibesensor.adapters.websocket.hub import WebSocketHub


def make_websocket() -> AsyncMock:
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def sent_json(ws: AsyncMock) -> dict[str, object]:
    return json.loads(ws.send_text.call_args[0][0])


async def build_hub(*selected_client_ids: str | None) -> tuple[WebSocketHub, list[AsyncMock]]:
    hub = WebSocketHub()
    websockets: list[AsyncMock] = []
    for selected_client_id in selected_client_ids:
        ws = make_websocket()
        await hub.add(ws, selected_client_id)
        websockets.append(ws)
    return hub, websockets
