"""WebSocket hub — fan-out broadcaster for live sensor payloads.

``WSHub`` maintains a set of active WebSocket connections and broadcasts
processed metric payloads to all subscribed clients with back-pressure
protection via per-connection send queues.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import WebSocket

from vibesensor.adapters.websocket.payload_orchestrator import PayloadBuildOrchestrator
from vibesensor.shared.types.payload_types import LiveWsPayload

LOGGER = logging.getLogger(__name__)

__all__ = ["WSConnection", "WebSocketHub"]


def _ws_debug_enabled() -> bool:
    """Check WS debug flag at call time so it can be toggled at runtime."""
    return os.environ.get("VIBESENSOR_WS_DEBUG", "0") == "1"


# Timing constants for WebSocket broadcast
_SEND_TIMEOUT_S: float = 0.5
"""Per-connection send timeout; connections exceeding this are dropped."""

_SEND_ERROR_LOG_INTERVAL_S: float = 10.0
"""Minimum interval between logged send-error warnings to avoid log spam."""

_MAX_CONSECUTIVE_FAILURES: int = 10
"""Back off after this many consecutive broadcast tick failures."""

_BACKOFF_MULTIPLIER: int = 5
"""Sleep multiplier applied to the tick interval during error back-off."""


@dataclass(slots=True)
class WSConnection:
    """Tracks a single active WebSocket connection and its selected client filter."""

    connection_id: int
    websocket: WebSocket
    selected_client_id: str | None = None
    closing: bool = False


@dataclass(frozen=True, slots=True)
class _WSConnectionSnapshot:
    """Immutable point-in-time connection view used by a broadcast tick."""

    connection_id: int
    websocket: WebSocket
    selected_client_id: str | None


class WebSocketHub:
    """Fan-out broadcaster: sends live metric payloads to all connected WebSocket clients."""

    def __init__(self) -> None:
        """Initialise the hub with an empty client registry."""
        self._connections: dict[int, WSConnection] = {}
        self._lock = asyncio.Lock()
        self._next_connection_id = 1
        self._send_timeout_s = _SEND_TIMEOUT_S
        self._last_send_error_log_ts = 0.0
        self._send_error_log_interval_s = _SEND_ERROR_LOG_INTERVAL_S

    async def add(self, websocket: WebSocket, selected_client_id: str | None) -> None:
        """Register *websocket* as a new active connection with an optional client filter."""
        async with self._lock:
            connection_id = self._next_connection_id
            self._next_connection_id += 1
            self._connections[id(websocket)] = WSConnection(
                connection_id=connection_id,
                websocket=websocket,
                selected_client_id=selected_client_id,
            )

    def connection_count(self) -> int:
        """Return an approximate count of active connections.

        Uses ``len()`` on the internal dict, which is atomic in CPython, so
        no lock is acquired.  The value may be stale by the time the caller
        acts on it; use ``_snapshot()`` when a consistent view is needed.
        """
        return len(self._connections)

    async def remove(self, websocket: WebSocket) -> None:
        """Deregister *websocket* from the hub."""
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

    async def _snapshot(self) -> list[_WSConnectionSnapshot]:
        """Return a point-in-time copy of the active connections list."""
        async with self._lock:
            return [
                _WSConnectionSnapshot(
                    connection_id=conn.connection_id,
                    websocket=conn.websocket,
                    selected_client_id=conn.selected_client_id,
                )
                for conn in self._connections.values()
                if not conn.closing
            ]

    async def _is_snapshot_current(self, conn: _WSConnectionSnapshot) -> bool:
        """Return True when *conn* still refers to the currently registered connection."""
        async with self._lock:
            current = self._connections.get(id(conn.websocket))
            return bool(
                current is not None
                and not current.closing
                and current.connection_id == conn.connection_id,
            )

    async def _current_selected_client_id(
        self,
        conn: _WSConnectionSnapshot,
    ) -> tuple[bool, str | None]:
        """Return the live selected client for *conn* when the connection is still current."""
        async with self._lock:
            current = self._connections.get(id(conn.websocket))
            if current is None or current.closing or current.connection_id != conn.connection_id:
                return False, None
            return True, current.selected_client_id

    async def _mark_snapshot_closing(self, conn: _WSConnectionSnapshot) -> bool:
        """Mark *conn* as closing if it is still the active registered connection."""
        async with self._lock:
            current = self._connections.get(id(conn.websocket))
            if current is None or current.connection_id != conn.connection_id:
                return False
            current.closing = True
            return True

    async def _remove_snapshot(self, conn: _WSConnectionSnapshot) -> None:
        """Remove *conn* only when the same generation is still registered."""
        async with self._lock:
            current = self._connections.get(id(conn.websocket))
            if current is not None and current.connection_id == conn.connection_id:
                self._connections.pop(id(conn.websocket), None)

    async def _send_conn(
        self,
        conn: _WSConnectionSnapshot,
        payload_text: str,
        *,
        selected_client_id: str | None,
    ) -> _WSConnectionSnapshot | None:
        """Send the appropriate payload to *conn*, return the WebSocket on failure."""
        if not await self._is_snapshot_current(conn):
            return None
        try:
            await asyncio.wait_for(
                conn.websocket.send_text(payload_text),
                timeout=self._send_timeout_s,
            )
            return None
        except Exception:
            now = asyncio.get_running_loop().time()
            if (now - self._last_send_error_log_ts) >= self._send_error_log_interval_s:
                self._last_send_error_log_ts = now
                LOGGER.warning(
                    "WebSocket broadcast send failed (selected_client=%r); "
                    "connection will be removed.",
                    selected_client_id,
                    exc_info=True,
                )
            if await self._mark_snapshot_closing(conn):
                return conn
            return None

    async def _send_current_conn(
        self,
        conn: _WSConnectionSnapshot,
        payloads: PayloadBuildOrchestrator,
        sent_selected_client_ids: dict[int, str | None],
    ) -> _WSConnectionSnapshot | None:
        """Send a payload built for the connection's current selection."""
        is_current, selected_client_id = await self._current_selected_client_id(conn)
        if not is_current:
            return None
        payload_text = await payloads.get_or_build_payload_text(selected_client_id)
        still_current, latest_selected_client_id = await self._current_selected_client_id(conn)
        if not still_current:
            return None
        if latest_selected_client_id != selected_client_id:
            selected_client_id = latest_selected_client_id
            payload_text = await payloads.get_or_build_payload_text(selected_client_id)
        sent_selected_client_ids[conn.connection_id] = selected_client_id
        return await self._send_conn(
            conn,
            payload_text,
            selected_client_id=selected_client_id,
        )

    async def broadcast(
        self,
        payload_builder: Callable[[str | None], LiveWsPayload],
    ) -> None:
        """Broadcast a live metric payload to all connected WebSocket clients.

        Calls *payload_builder* at most once per unique ``selected_client_id``
        observed during the tick (results are cached per tick). Connections that
        fail or time out during send are removed from the hub automatically.
        """
        conns = await self._snapshot()
        if not conns:
            return
        payloads = PayloadBuildOrchestrator(
            payload_builder,
            capture_debug=_ws_debug_enabled(),
        )
        await payloads.prepare(conn.selected_client_id for conn in conns)
        sent_selected_client_ids: dict[int, str | None] = {}

        dead_ws = await asyncio.gather(
            *(
                self._send_current_conn(
                    conn,
                    payloads,
                    sent_selected_client_ids,
                )
                for conn in conns
            ),
        )
        for conn in dead_ws:
            if conn is not None:
                with contextlib.suppress(Exception):
                    await conn.websocket.close()
                await self._remove_snapshot(conn)
        if payloads.failed_client_ids:
            # Count how many connections were affected by build failures.
            affected = sum(
                1
                for selected_client_id in sent_selected_client_ids.values()
                if selected_client_id in payloads.failed_client_ids
            )
            LOGGER.error(
                "WebSocket payload build failed for %d client id(s) (%s); "
                "%d connection(s) received error payloads.",
                len(payloads.failed_client_ids),
                ", ".join(repr(cid) for cid in payloads.failed_client_ids),
                affected,
            )

        # Dev-only instrumentation: log payload sizes when VIBESENSOR_WS_DEBUG=1.
        if payloads.debug_info is not None and payloads.payload_cache:
            live_count = len(conns) - sum(1 for ws in dead_ws if ws is not None)
            for sel_id, text in payloads.payload_cache.items():
                LOGGER.debug(
                    "WS_DEBUG selected=%r size_bytes=%d connections=%d per_client_freq=%s",
                    sel_id,
                    len(text),
                    live_count,
                    payloads.debug_info.get(sel_id, False),
                )

    async def run(
        self,
        hz: int,
        payload_builder: Callable[[str | None], LiveWsPayload],
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        """Drive broadcast ticks at *hz* frames per second until cancelled.

        *on_tick* (if provided) is called synchronously before each broadcast so
        the caller can update shared state atomically with payload generation.
        Consecutive broadcast failures trigger back-off to avoid thundering-herd
        log spam.
        """
        if hz <= 0:
            LOGGER.warning(
                "WebSocketHub.run called with hz=%r; clamping to 1 Hz.",
                hz,
            )
        interval = 1.0 / max(1, hz)
        consecutive_failures = 0
        loop = asyncio.get_running_loop()
        while True:
            tick_start = loop.time()
            try:
                if on_tick is not None:
                    try:
                        on_tick()
                    except Exception:
                        LOGGER.warning(
                            "WebSocket on_tick callback raised; proceeding to broadcast.",
                            exc_info=True,
                        )
                await self.broadcast(payload_builder)
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    LOGGER.error(
                        "WebSocket broadcast tick failed %d consecutive times; backing off.",
                        consecutive_failures,
                        exc_info=True,
                    )
                    await asyncio.sleep(interval * _BACKOFF_MULTIPLIER)
                    # Reset the tick clock after the backoff sleep so the
                    # post-tick sleep uses the correct remaining time.
                    tick_start = loop.time()
                    consecutive_failures = 0
                else:
                    LOGGER.warning(
                        "WebSocket broadcast tick failed (%d consecutive); will retry.",
                        consecutive_failures,
                        exc_info=True,
                    )
            elapsed = loop.time() - tick_start
            await asyncio.sleep(max(0, interval - elapsed))
