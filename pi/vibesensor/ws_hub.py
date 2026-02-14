from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import WebSocket


@dataclass(slots=True)
class WSConnection:
    websocket: WebSocket
    selected_client_id: str | None = None


class WebSocketHub:
    def __init__(self):
        self._connections: dict[int, WSConnection] = {}
        self._lock = asyncio.Lock()
        self._send_timeout_s = 0.5

    async def add(self, websocket: WebSocket, selected_client_id: str | None) -> None:
        async with self._lock:
            self._connections[id(websocket)] = WSConnection(
                websocket=websocket,
                selected_client_id=selected_client_id,
            )

    async def remove(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(id(websocket), None)

    async def update_selected_client(self, websocket: WebSocket, client_id: str | None) -> None:
        async with self._lock:
            conn = self._connections.get(id(websocket))
            if conn is not None:
                conn.selected_client_id = client_id

    async def _snapshot(self) -> list[WSConnection]:
        async with self._lock:
            return list(self._connections.values())

    async def broadcast(
        self,
        payload_builder: Callable[[str | None], dict],
    ) -> None:
        conns = await self._snapshot()
        if not conns:
            return

        async def _send(conn: WSConnection) -> WebSocket | None:
            payload = payload_builder(conn.selected_client_id)
            try:
                await asyncio.wait_for(conn.websocket.send_json(payload), timeout=self._send_timeout_s)
                return None
            except Exception:
                return conn.websocket

        dead_ws = await asyncio.gather(*(_send(conn) for conn in conns))
        for ws in dead_ws:
            if ws is not None:
                await self.remove(ws)

    async def run(self, hz: int, payload_builder: Callable[[str | None], dict]) -> None:
        interval = 1.0 / max(1, hz)
        while True:
            await self.broadcast(payload_builder)
            await asyncio.sleep(interval)
