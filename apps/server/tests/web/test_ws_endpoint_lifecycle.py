"""/ws endpoint lifecycle: send-side drops end the endpoint; closing is idempotent."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.types import Message
from starlette.websockets import WebSocketDisconnect, WebSocketState

from vibesensor.web.websocket import _close_quietly, create_websocket_routes


class _DroppingBroadcaster:
    """Drops every connection as soon as it is added, like a failed first send."""

    def __init__(self) -> None:
        self.removed = 0

    def add(
        self, websocket: WebSocket, selected: str | None, *, on_drop: Callable[[], None]
    ) -> None:
        on_drop()

    def remove(self, websocket: WebSocket) -> None:
        self.removed += 1

    def select(self, websocket: WebSocket, client_id: str | None) -> None:
        raise AssertionError("not reached")


def test_broadcaster_drop_ends_endpoint_and_closes_socket_once() -> None:
    broadcaster = _DroppingBroadcaster()
    app = FastAPI()
    app.include_router(create_websocket_routes(broadcaster))  # type: ignore[arg-type]

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()

    assert closed.value.code == 1000
    assert broadcaster.removed == 1


async def _connected_websocket(sent: list[Message]) -> WebSocket:
    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        sent.append(message)

    ws = WebSocket({"type": "websocket", "path": "/ws", "headers": []}, receive, send)
    await ws.accept()
    return ws


async def test_close_quietly_is_idempotent_after_another_close() -> None:
    sent: list[Message] = []
    ws = await _connected_websocket(sent)
    await ws.close()  # e.g. a previous close after a send timeout

    await _close_quietly(ws)
    await _close_quietly(ws)

    assert [m["type"] for m in sent] == ["websocket.accept", "websocket.close"]
    assert ws.application_state is WebSocketState.DISCONNECTED


async def test_close_quietly_swallows_transport_errors() -> None:
    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        if message["type"] == "websocket.close":
            raise OSError("broken pipe")

    ws = WebSocket({"type": "websocket", "path": "/ws", "headers": []}, receive, send)
    await ws.accept()

    await _close_quietly(ws)

    assert ws.application_state is WebSocketState.DISCONNECTED
