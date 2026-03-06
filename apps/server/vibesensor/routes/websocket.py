"""WebSocket endpoint for real-time data streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..domain_models import normalize_sensor_id

if TYPE_CHECKING:
    from ..runtime import RuntimeState

__all__ = ["create_websocket_routes"]

LOGGER = logging.getLogger(__name__)

# Idle receive timeout: if a connected client sends no message for this many
# seconds the server assumes the connection is a zombie (TCP half-open) and
# closes it.  Normal dashboard sessions only send messages when changing the
# selected sensor, so this is intentionally long.
_RECEIVE_IDLE_TIMEOUT_S: float = 300.0


def create_websocket_routes(state: RuntimeState) -> APIRouter:
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
        await state.ws_hub.add(ws, selected)
        _loads = json.loads
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
                try:
                    payload = _loads(message)
                except json.JSONDecodeError:
                    LOGGER.debug("Ignoring malformed WS message (not valid JSON)")
                    continue
                if isinstance(payload, dict) and "client_id" in payload:
                    value = payload["client_id"]
                    try:
                        if value is None:
                            await state.ws_hub.update_selected_client(ws, None)
                        elif isinstance(value, str):
                            normalized = normalize_sensor_id(value)
                            await state.ws_hub.update_selected_client(ws, normalized)
                    except ValueError:
                        continue
                    except Exception:
                        LOGGER.debug("Error processing WS message", exc_info=True)
                        continue
        except WebSocketDisconnect:
            LOGGER.debug("WebSocket client disconnected")
        except Exception:
            LOGGER.warning("WebSocket handler error", exc_info=True)
        finally:
            await state.ws_hub.remove(ws)

    return router
