"""WebSocket endpoint for real-time data streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from vibesensor.adapters.http.ws_message_router import route_ws_message
from vibesensor.domain import normalize_sensor_id

if TYPE_CHECKING:
    from vibesensor.adapters.websocket.hub import WebSocketHub

__all__ = ["create_websocket_routes"]

LOGGER = logging.getLogger(__name__)

# Idle receive timeout: if a connected client sends no message for this many
# seconds the server assumes the connection is a zombie (TCP half-open) and
# closes it.  Normal dashboard sessions only send messages when changing the
# selected sensor, so this is intentionally long.
_RECEIVE_IDLE_TIMEOUT_S: float = 300.0


def create_websocket_routes(ws_hub: WebSocketHub) -> APIRouter:
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
        await ws_hub.add(ws, selected)
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        ws.receive_text(),
                        timeout=_RECEIVE_IDLE_TIMEOUT_S,
                    )
                except TimeoutError:
                    LOGGER.debug(
                        "WebSocket client idle for %.0fs; closing zombie connection.",
                        _RECEIVE_IDLE_TIMEOUT_S,
                    )
                    await ws.close()
                    return
                await route_ws_message(ws_hub, ws, message)
        except WebSocketDisconnect:
            LOGGER.debug("WebSocket client disconnected")
        finally:
            await ws_hub.remove(ws)

    return router
