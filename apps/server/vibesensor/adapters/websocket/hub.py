"""WebSocket hub — fan-out broadcaster for live sensor payloads.

``WSHub`` maintains a set of active WebSocket connections and broadcasts
processed metric payloads to all subscribed clients with back-pressure
protection via per-connection send queues.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import WebSocket

from vibesensor.adapters.websocket.broadcast_runner import BroadcastRunner
from vibesensor.adapters.websocket.connection_tracker import (
    ConnectionTracker,
    WSConnection,
    WSConnectionSnapshot,
)
from vibesensor.adapters.websocket.tick_controller import BroadcastTickController
from vibesensor.app.process_settings import load_websocket_env_settings
from vibesensor.shared.types.payload_types import LiveWsPayload

LOGGER = logging.getLogger(__name__)

__all__ = ["WSConnection", "WebSocketHub"]


def _ws_debug_enabled() -> bool:
    """Check WS debug flag at call time so it can be toggled at runtime."""
    return load_websocket_env_settings().ws_debug


# Timing constants for WebSocket broadcast
_SEND_TIMEOUT_S: float = 0.5
"""Per-connection send timeout; connections exceeding this are dropped."""

_SEND_ERROR_LOG_INTERVAL_S: float = 10.0
"""Minimum interval between logged send-error warnings to avoid log spam."""


class WebSocketHub:
    """Fan-out broadcaster: sends live metric payloads to all connected WebSocket clients."""

    def __init__(self) -> None:
        """Initialise the hub with an empty client registry."""
        self._tracker = ConnectionTracker()
        self._runner = BroadcastRunner(
            self._tracker,
            send_timeout_s=_SEND_TIMEOUT_S,
            send_error_log_interval_s=_SEND_ERROR_LOG_INTERVAL_S,
        )

    async def add(self, websocket: WebSocket, selected_client_id: str | None) -> None:
        """Register *websocket* as a new active connection with an optional client filter."""
        await self._tracker.add(websocket, selected_client_id)

    def connection_count(self) -> int:
        """Return an approximate count of active connections."""
        return self._tracker.connection_count()

    async def remove(self, websocket: WebSocket) -> None:
        """Deregister *websocket* from the hub."""
        await self._tracker.remove(websocket)

    async def update_selected_client(self, websocket: WebSocket, client_id: str | None) -> None:
        """Update the client-filter for an existing connection."""
        await self._tracker.update_selected_client(websocket, client_id)

    async def _snapshot(self) -> list[WSConnectionSnapshot]:
        """Return a point-in-time copy of the active connections list."""
        return await self._tracker.snapshot()

    async def broadcast(
        self,
        payload_builder: Callable[[str | None], LiveWsPayload],
    ) -> None:
        """Broadcast a live metric payload to all connected WebSocket clients.

        Calls *payload_builder* at most once per unique ``selected_client_id``
        observed during the tick (results are cached per tick). Connections that
        fail or time out during send are removed from the hub automatically.
        """
        await self._runner.broadcast(
            payload_builder,
            capture_debug=_ws_debug_enabled(),
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
        Repeated broadcast failures escalate out to the managed task supervisor,
        which owns restart/backoff policy and health reporting for the
        background ws-broadcast loop.
        """
        controller = BroadcastTickController(hz=hz, logger=LOGGER)
        await controller.run(
            broadcast_tick=lambda: self.broadcast(payload_builder),
            on_tick=on_tick,
        )
