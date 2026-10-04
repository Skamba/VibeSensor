"""WebSocket endpoint for real-time data streaming.

The browser only sends a message when it connects or changes the selected
sensor, so a passive viewer can stay silent for hours. Dead peers are detected
on the send side: the broadcaster pushes the live payload several times per
second and drops a connection whose send fails or times out, which cancels this
endpoint's receive loop through ``on_drop``.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import anyio
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from vibesensor.domain.sensor import normalize_sensor_id
from vibesensor.web.ws_message_router import route_ws_message

if TYPE_CHECKING:
    from vibesensor.live.broadcaster import LiveBroadcaster

__all__ = ["create_websocket_routes"]

LOGGER = logging.getLogger(__name__)

_CLOSE_TIMEOUT_S = 1.0
"""Upper bound for sending the close frame to a peer that may be gone."""


async def _close_quietly(ws: WebSocket) -> None:
    """Close *ws* once; a no-op when either side already closed it."""
    if (
        ws.application_state is not WebSocketState.CONNECTED
        or ws.client_state is WebSocketState.DISCONNECTED
    ):
        return
    with (
        anyio.move_on_after(_CLOSE_TIMEOUT_S, shield=True),
        contextlib.suppress(WebSocketDisconnect, RuntimeError, OSError),
    ):
        await ws.close()


def create_websocket_routes(broadcaster: LiveBroadcaster) -> APIRouter:
    """Create and return the WebSocket streaming routes."""
    router = APIRouter()

    @router.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        selected = ws.query_params.get("client_id")
        if selected is not None:
            try:
                selected = normalize_sensor_id(selected)
            except ValueError:
                selected = None
        await ws.accept()
        try:
            with anyio.CancelScope() as receive_scope:
                broadcaster.add(ws, selected, on_drop=receive_scope.cancel)
                while True:
                    message = await ws.receive_text()
                    route_ws_message(broadcaster, ws, message)
        except WebSocketDisconnect:
            LOGGER.debug("WebSocket client disconnected")
        finally:
            broadcaster.remove(ws)
            await _close_quietly(ws)

    return router
