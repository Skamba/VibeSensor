"""Connection-generation tracker for the WebSocket broadcast hub.

Owns connection state, generation numbering, and stale-snapshot
detection so that ``WebSocketHub`` can focus on broadcast orchestration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import WebSocket

__all__ = ["ConnectionTracker", "WSConnection", "WSConnectionSnapshot"]


@dataclass(slots=True)
class WSConnection:
    """Tracks a single active WebSocket connection and its selected client filter."""

    connection_id: int
    websocket: WebSocket
    selected_client_id: str | None = None
    closing: bool = False


@dataclass(frozen=True, slots=True)
class WSConnectionSnapshot:
    """Immutable point-in-time connection view used by a broadcast tick."""

    connection_id: int
    websocket: WebSocket
    selected_client_id: str | None


class ConnectionTracker:
    """Manages WebSocket connection state with generation-based TOCTOU protection."""

    def __init__(self) -> None:
        self._connections: dict[int, WSConnection] = {}
        self._lock = asyncio.Lock()
        self._next_connection_id = 1

    async def add(self, websocket: WebSocket, selected_client_id: str | None) -> None:
        """Register *websocket* as a new active connection."""
        async with self._lock:
            connection_id = self._next_connection_id
            self._next_connection_id += 1
            self._connections[id(websocket)] = WSConnection(
                connection_id=connection_id,
                websocket=websocket,
                selected_client_id=selected_client_id,
            )

    def connection_count(self) -> int:
        """Return an approximate count of active connections (lock-free)."""
        return len(self._connections)

    async def remove(self, websocket: WebSocket) -> None:
        """Deregister *websocket* from the tracker."""
        async with self._lock:
            conn = self._connections.pop(id(websocket), None)
            if conn is not None:
                conn.closing = True

    async def update_selected_client(self, websocket: WebSocket, client_id: str | None) -> None:
        """Update the client-filter for an existing connection."""
        async with self._lock:
            conn = self._connections.get(id(websocket))
            if conn is not None:
                conn.selected_client_id = client_id

    async def snapshot(self) -> list[WSConnectionSnapshot]:
        """Return a point-in-time copy of the active connections list."""
        async with self._lock:
            return [
                WSConnectionSnapshot(
                    connection_id=conn.connection_id,
                    websocket=conn.websocket,
                    selected_client_id=conn.selected_client_id,
                )
                for conn in self._connections.values()
                if not conn.closing
            ]

    async def is_snapshot_current(self, conn: WSConnectionSnapshot) -> bool:
        """Return True when *conn* still refers to the currently registered connection."""
        async with self._lock:
            current = self._connections.get(id(conn.websocket))
            return bool(
                current is not None
                and not current.closing
                and current.connection_id == conn.connection_id,
            )

    async def current_selected_client_id(
        self,
        conn: WSConnectionSnapshot,
    ) -> tuple[bool, str | None]:
        """Return the live selected client for *conn* when the connection is still current."""
        async with self._lock:
            current = self._connections.get(id(conn.websocket))
            if current is None or current.closing or current.connection_id != conn.connection_id:
                return False, None
            return True, current.selected_client_id

    async def mark_snapshot_closing(self, conn: WSConnectionSnapshot) -> bool:
        """Mark *conn* as closing if it is still the active registered connection."""
        async with self._lock:
            current = self._connections.get(id(conn.websocket))
            if current is None or current.connection_id != conn.connection_id:
                return False
            current.closing = True
            return True

    async def remove_snapshot(self, conn: WSConnectionSnapshot) -> None:
        """Remove *conn* only when the same generation is still registered."""
        async with self._lock:
            current = self._connections.get(id(conn.websocket))
            if current is not None and current.connection_id == conn.connection_id:
                self._connections.pop(id(conn.websocket), None)
