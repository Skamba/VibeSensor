"""WebSocket client-message parsing and routing."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import WebSocket
from pydantic import TypeAdapter, ValidationError

from vibesensor.domain.sensor import normalize_sensor_id
from vibesensor.live.payload_types import WsClientSelectionPayload

if TYPE_CHECKING:
    from vibesensor.live.broadcaster import LiveBroadcaster

LOGGER = logging.getLogger(__name__)

_WS_CLIENT_SELECTION_ADAPTER = TypeAdapter(WsClientSelectionPayload)


def route_ws_message(
    broadcaster: LiveBroadcaster,
    ws: WebSocket,
    message: str,
) -> None:
    """Parse one client message and apply supported websocket actions."""

    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        LOGGER.debug("Ignoring malformed WS message (not valid JSON)")
        return
    if not isinstance(payload, dict):
        LOGGER.debug(
            "Ignoring WS message with unexpected type %s (expected dict)",
            type(payload).__name__,
        )
        return
    try:
        typed_payload = _WS_CLIENT_SELECTION_ADAPTER.validate_python(payload)
    except ValidationError:
        LOGGER.debug("Ignoring invalid WS message payload: %r", payload)
        return
    if "client_id" not in typed_payload:
        LOGGER.debug(
            "Ignoring WS message dict with no recognized keys: %s",
            list(payload.keys()),
        )
        return
    value = typed_payload["client_id"]
    if value is None:
        broadcaster.select(ws, None)
        return
    try:
        normalized = normalize_sensor_id(value)
    except ValueError:
        LOGGER.debug(
            "Ignoring invalid client_id value in WS message: %r",
            value,
        )
        return
    broadcaster.select(ws, normalized)
