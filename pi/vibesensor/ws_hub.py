from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import WebSocket

LOGGER = logging.getLogger(__name__)

# Timing constants for WebSocket broadcast
_SEND_TIMEOUT_S: float = 0.5
"""Per-connection send timeout; connections exceeding this are dropped."""

_SEND_ERROR_LOG_INTERVAL_S: float = 10.0
"""Minimum interval between logged send-error warnings to avoid log spam."""


@dataclass(slots=True)
class WSConnection:
    websocket: WebSocket
    selected_client_id: str | None = None


class WebSocketHub:
    def __init__(self):
        self._connections: dict[int, WSConnection] = {}
        self._lock = asyncio.Lock()
        self._send_timeout_s = _SEND_TIMEOUT_S
        self._last_send_error_log_ts = 0.0
        self._send_error_log_interval_s = _SEND_ERROR_LOG_INTERVAL_S

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
                await asyncio.wait_for(
                    conn.websocket.send_json(payload),
                    timeout=self._send_timeout_s,
                )
                return None
            except Exception:
                now = asyncio.get_running_loop().time()
                if (now - self._last_send_error_log_ts) >= self._send_error_log_interval_s:
                    self._last_send_error_log_ts = now
                    LOGGER.warning(
                        "WebSocket broadcast send failed; connection will be removed.",
                        exc_info=True,
                    )
                return conn.websocket

        dead_ws = await asyncio.gather(*(_send(conn) for conn in conns))
        for ws in dead_ws:
            if ws is not None:
                await self.remove(ws)

    async def run(
        self,
        hz: int,
        payload_builder: Callable[[str | None], dict],
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        interval = 1.0 / max(1, hz)
        while True:
            if on_tick is not None:
                on_tick()
            await self.broadcast(payload_builder)
            await asyncio.sleep(interval)
