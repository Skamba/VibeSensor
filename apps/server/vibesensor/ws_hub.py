"""WebSocket hub — fan-out broadcaster for live sensor payloads.

``WSHub`` maintains a set of active WebSocket connections and broadcasts
processed metric payloads to all subscribed clients with back-pressure
protection via per-connection send queues.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import WebSocket

from .json_utils import sanitize_for_json

LOGGER = logging.getLogger(__name__)


def _ws_debug_enabled() -> bool:
    """Check WS debug flag at call time so it can be toggled at runtime."""
    return os.environ.get("VIBESENSOR_WS_DEBUG", "0") == "1"


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

_MAX_CONSECUTIVE_FAILURES: int = 10
"""Back off after this many consecutive broadcast tick failures."""


@dataclass(slots=True)
class WSConnection:
    websocket: WebSocket
    selected_client_id: str | None = None


class WebSocketHub:
    def __init__(self) -> None:
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

    def _build_payload_for(
        self,
        selected_client_id: str | None,
        payload_builder: Callable[[str | None], dict],
        payload_cache: dict[str | None, str],
        failed_client_ids: set[str | None],
        debug_info: dict[str | None, bool] | None = None,
    ) -> str:
        """Build and cache the JSON payload for *selected_client_id*.

        On failure the error payload is cached and an ERROR log is
        emitted (once per failing client_id per tick).

        When *debug_info* is provided (``VIBESENSOR_WS_DEBUG=1``), the method
        inspects the pre-serialisation dict and records whether per-client
        frequency data is present, avoiding a redundant ``json.loads()`` later.
        """
        if selected_client_id in payload_cache:
            return payload_cache[selected_client_id]
        _dumps = json.dumps  # local-bind for hot-path
        try:
            raw_payload = payload_builder(selected_client_id)
            cleaned, had_non_finite = sanitize_for_json(raw_payload)
            if had_non_finite:
                LOGGER.warning(
                    "WebSocket payload for client %r contained NaN/Inf values; replaced with null.",
                    selected_client_id,
                )
            if debug_info is not None:
                # Inspect the pre-serialised dict; avoids a redundant json.loads().
                has_freq = False
                try:
                    spectra = cleaned.get("spectra") if isinstance(cleaned, dict) else None
                    if isinstance(spectra, dict):
                        for _cid, cs in (spectra.get("clients") or {}).items():
                            if isinstance(cs, dict) and cs.get("freq"):
                                has_freq = True
                                break
                except Exception:
                    LOGGER.debug("Debug freq-inspection failed", exc_info=True)
                debug_info[selected_client_id] = has_freq
            text = _dumps(
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

    async def _send_conn(
        self,
        conn: WSConnection,
        payload_builder: Callable[[str | None], dict],
        payload_cache: dict[str | None, str],
        failed_client_ids: set[str | None],
        debug_info: dict[str | None, bool] | None = None,
    ) -> WebSocket | None:
        """Send the appropriate payload to *conn*, return the WebSocket on failure."""
        payload_text = self._build_payload_for(
            conn.selected_client_id,
            payload_builder,
            payload_cache,
            failed_client_ids,
            debug_info=debug_info,
        )
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

    async def broadcast(
        self,
        payload_builder: Callable[[str | None], dict],
    ) -> None:
        conns = await self._snapshot()
        if not conns:
            return
        payload_cache: dict[str | None, str] = {}
        failed_client_ids: set[str | None] = set()
        # Collect debug inspection data during build (avoids redundant json.loads later).
        debug_info: dict[str | None, bool] | None = {} if _ws_debug_enabled() else None

        dead_ws = await asyncio.gather(
            *(
                self._send_conn(
                    conn,
                    payload_builder,
                    payload_cache,
                    failed_client_ids,
                    debug_info=debug_info,
                )
                for conn in conns
            )
        )
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

        # Dev-only instrumentation: log payload sizes when VIBESENSOR_WS_DEBUG=1.
        if debug_info is not None and payload_cache:
            for sel_id, text in payload_cache.items():
                LOGGER.debug(
                    "WS_DEBUG selected=%r size_bytes=%d connections=%d per_client_freq=%s",
                    sel_id,
                    len(text),
                    len(conns),
                    debug_info.get(sel_id, False),
                )

    async def run(
        self,
        hz: int,
        payload_builder: Callable[[str | None], dict],
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        interval = 1.0 / max(1, hz)
        _consecutive_failures = 0
        loop = asyncio.get_running_loop()
        while True:
            tick_start = loop.time()
            try:
                if on_tick is not None:
                    on_tick()
                await self.broadcast(payload_builder)
                _consecutive_failures = 0
            except Exception:
                _consecutive_failures += 1
                if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    LOGGER.error(
                        "WebSocket broadcast tick failed %d consecutive times; backing off.",
                        _consecutive_failures,
                        exc_info=True,
                    )
                    await asyncio.sleep(interval * 5)
                    _consecutive_failures = 0
                else:
                    LOGGER.warning("WebSocket broadcast tick failed; will retry.", exc_info=True)
            elapsed = loop.time() - tick_start
            await asyncio.sleep(max(0, interval - elapsed))
