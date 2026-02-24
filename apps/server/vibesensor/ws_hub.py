from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

LOGGER = logging.getLogger(__name__)


def sanitize_for_json(obj: Any) -> tuple[Any, bool]:
    """Recursively replace non-finite floats (NaN, Inf, -Inf) with ``None``.

    This ensures the resulting structure can be serialised with
    ``json.dumps(allow_nan=False)`` and produces RFC-8259 compliant JSON that
    any standard ``JSON.parse()`` implementation can consume.

    Returns the sanitised object and a boolean flag indicating whether any
    non-finite value was encountered.
    """
    found_non_finite = False

    def _walk(v: Any) -> Any:
        nonlocal found_non_finite
        if isinstance(v, float):
            if math.isfinite(v):
                return v
            found_non_finite = True
            return None
        if isinstance(v, dict):
            return {k: _walk(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [_walk(item) for item in v]
        return v

    cleaned = _walk(obj)
    return cleaned, found_non_finite


# Timing constants for WebSocket broadcast
_SEND_TIMEOUT_S: float = 0.5
"""Per-connection send timeout; connections exceeding this are dropped."""

_SEND_ERROR_LOG_INTERVAL_S: float = 10.0
"""Minimum interval between logged send-error warnings to avoid log spam."""

_ERROR_PAYLOAD: str = json.dumps(
    {"error": "payload_build_failed"},
    separators=(",", ":"),
)
"""Pre-serialised error payload sent to clients when their payload build fails."""


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
        payload_cache: dict[str | None, str] = {}
        # Track which client IDs had build failures this tick so we can
        # report an accurate count without excessive per-connection logging.
        failed_client_ids: set[str | None] = set()

        def _build_payload(selected_client_id: str | None) -> str:
            """Build and cache the JSON payload for *selected_client_id*.

            On failure the error payload is cached and an ERROR log is
            emitted (once per failing client_id per tick).
            """
            if selected_client_id in payload_cache:
                return payload_cache[selected_client_id]
            try:
                raw_payload = payload_builder(selected_client_id)
                cleaned, had_non_finite = sanitize_for_json(raw_payload)
                if had_non_finite:
                    LOGGER.warning(
                        "WebSocket payload for client %r contained NaN/Inf "
                        "values; replaced with null.",
                        selected_client_id,
                    )
                text = json.dumps(
                    cleaned,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            except Exception:
                LOGGER.error(
                    "WebSocket payload build failed for client %r; "
                    "sending error payload to affected connections.",
                    selected_client_id,
                    exc_info=True,
                )
                failed_client_ids.add(selected_client_id)
                text = _ERROR_PAYLOAD
            payload_cache[selected_client_id] = text
            return text

        async def _send(conn: WSConnection) -> WebSocket | None:
            payload_text = _build_payload(conn.selected_client_id)
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
                        "WebSocket broadcast send failed; connection will be removed.",
                        exc_info=True,
                    )
                return conn.websocket

        dead_ws = await asyncio.gather(*(_send(conn) for conn in conns))
        for ws in dead_ws:
            if ws is not None:
                await self.remove(ws)
        if failed_client_ids:
            # Count how many connections were affected by build failures.
            affected = sum(1 for c in conns if c.selected_client_id in failed_client_ids)
            LOGGER.error(
                "Payload build failed for %d client id(s) (%s); "
                "%d connection(s) received error payloads.",
                len(failed_client_ids),
                ", ".join(repr(cid) for cid in failed_client_ids),
                affected,
            )

    async def run(
        self,
        hz: int,
        payload_builder: Callable[[str | None], dict],
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        interval = 1.0 / max(1, hz)
        while True:
            try:
                if on_tick is not None:
                    on_tick()
                await self.broadcast(payload_builder)
            except Exception:
                LOGGER.warning("WebSocket broadcast tick failed; will retry.", exc_info=True)
            await asyncio.sleep(interval)
