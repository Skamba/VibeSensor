"""Live WebSocket broadcaster.

One task per app builds the live payload at the UI push rate and sends it to
every connected browser. Spectra ("heavy" data) are included on a subset of
ticks. A socket whose send fails or exceeds the send timeout is closed and
dropped; the browser reconnects on its own.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import Protocol

import anyio
from fastapi import WebSocket

from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.json_utils import json_text_dumps, sanitize_for_json
from vibesensor.shared.runtime_failures import BroadcastTickLoopFailure
from vibesensor.shared.types.payload_types import LiveWsPayload, WsErrorPayload

__all__ = ["ERROR_PAYLOAD_TEXT", "LiveBroadcaster", "LivePayloadSource"]

LOGGER = logging.getLogger(__name__)

SEND_TIMEOUT_S = 0.5
"""Per-connection send timeout; slower connections are dropped."""

_SEND_ERROR_LOG_INTERVAL_S = 10.0
_MAX_CONSECUTIVE_TICK_FAILURES = 10
_SEND_FAILURE_EXCEPTIONS = (OSError, RuntimeError, TimeoutError)
_BUILD_FAILURE_EXCEPTIONS = (
    TypeError,
    ValueError,
    OverflowError,
    KeyError,
    AttributeError,
    RuntimeError,
)
_ERROR_PAYLOAD: WsErrorPayload = {"error": "payload_build_failed"}
ERROR_PAYLOAD_TEXT = json_text_dumps(_ERROR_PAYLOAD)


class LivePayloadSource(Protocol):
    """Builds the live payload shared by all connections for one tick."""

    def build_shared_payload(self, *, include_heavy: bool) -> LiveWsPayload: ...


@dataclass(eq=False, slots=True)
class _Connection:
    websocket: WebSocket
    selected_client_id: str | None


class LiveBroadcaster:
    """Track connected browsers and push the live payload to them at a fixed rate."""

    def __init__(
        self,
        *,
        payload_source: LivePayloadSource,
        ingest_diagnostics: IngestDiagnosticsCollector,
        push_hz: int,
        heavy_push_hz: int,
    ) -> None:
        self._payload_source = payload_source
        self._ingest_diagnostics = ingest_diagnostics
        self._push_hz = max(1, push_hz)
        self._heavy_push_hz = max(1, heavy_push_hz)
        self._heavy_credit = 0
        self._connections: dict[int, _Connection] = {}
        self._last_send_error_log_s = float("-inf")

    # -- connections (called from the /ws route on the event loop) ------------

    def add(self, websocket: WebSocket, selected_client_id: str | None) -> None:
        self._connections[id(websocket)] = _Connection(websocket, selected_client_id)

    def remove(self, websocket: WebSocket) -> None:
        self._connections.pop(id(websocket), None)

    def select(self, websocket: WebSocket, client_id: str | None) -> None:
        """Change which sensor *websocket* has selected."""
        conn = self._connections.get(id(websocket))
        if conn is not None:
            conn.selected_client_id = client_id

    def connection_count(self) -> int:
        return len(self._connections)

    # -- broadcasting ----------------------------------------------------------

    def _next_tick_includes_heavy(self) -> bool:
        """Spread heavy ticks evenly: ``heavy_push_hz`` of every ``push_hz`` ticks."""
        if self._heavy_push_hz >= self._push_hz:
            return True
        self._heavy_credit += self._heavy_push_hz
        if self._heavy_credit < self._push_hz:
            return False
        self._heavy_credit -= self._push_hz
        return True

    async def broadcast(self, *, include_heavy: bool) -> None:
        """Build the payload once and send it to every current connection."""
        connections = list(self._connections.values())
        if not connections:
            return
        try:
            shared: LiveWsPayload | None = self._payload_source.build_shared_payload(
                include_heavy=include_heavy,
            )
        except _BUILD_FAILURE_EXCEPTIONS:
            LOGGER.error(
                "WebSocket payload build failed; sending error payload to %d connection(s).",
                len(connections),
                exc_info=True,
            )
            shared = None

        texts: dict[str | None, str] = {}
        for conn in connections:
            selected = conn.selected_client_id
            if selected not in texts:
                texts[selected] = (
                    ERROR_PAYLOAD_TEXT
                    if shared is None
                    else await anyio.to_thread.run_sync(_serialize, shared, selected)
                )
        async with anyio.create_task_group() as task_group:
            for conn in connections:
                task_group.start_soon(self._send, conn, texts[conn.selected_client_id])

    async def _send(self, conn: _Connection, text: str) -> None:
        try:
            with anyio.fail_after(SEND_TIMEOUT_S):
                await conn.websocket.send_text(text)
        except _SEND_FAILURE_EXCEPTIONS:
            now = anyio.current_time()
            if now - self._last_send_error_log_s >= _SEND_ERROR_LOG_INTERVAL_S:
                self._last_send_error_log_s = now
                LOGGER.warning(
                    "WebSocket send failed (selected_client=%r); dropping connection.",
                    conn.selected_client_id,
                    exc_info=True,
                )
            if self._connections.get(id(conn.websocket)) is conn:
                del self._connections[id(conn.websocket)]
            with contextlib.suppress(OSError, RuntimeError):
                await conn.websocket.close()

    async def run(self) -> None:
        """Broadcast at ``push_hz`` until cancelled.

        Repeated ``OSError`` ticks escalate as :class:`BroadcastTickLoopFailure` so the
        task supervisor owns restart/backoff and health reporting.
        """
        interval_s = 1.0 / self._push_hz
        consecutive_failures = 0
        while True:
            tick_start = anyio.current_time()
            include_heavy = self._next_tick_includes_heavy()
            try:
                await self.broadcast(include_heavy=include_heavy)
            except OSError as exc:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_TICK_FAILURES:
                    LOGGER.error(
                        "WebSocket broadcast tick failed %d consecutive times; escalating.",
                        consecutive_failures,
                        exc_info=True,
                    )
                    raise BroadcastTickLoopFailure(
                        consecutive_failures=consecutive_failures,
                        cause=exc,
                    ) from exc
                LOGGER.warning(
                    "WebSocket broadcast tick failed (%d consecutive); will retry.",
                    consecutive_failures,
                    exc_info=True,
                )
            else:
                consecutive_failures = 0
                self._ingest_diagnostics.note_ws_publish(
                    connection_count=len(self._connections),
                    duration_s=max(0.0, anyio.current_time() - tick_start),
                )
            await anyio.sleep(max(0.0, interval_s - (anyio.current_time() - tick_start)))


def _serialize(shared: LiveWsPayload, selected_client_id: str | None) -> str:
    """Serialize the payload for one selection; defaults to the first client."""
    clients = shared["clients"]
    active = selected_client_id
    if active is None and clients:
        active = clients[0]["id"]
    payload: LiveWsPayload = {**shared, "selected_client_id": active}
    try:
        try:
            return json_text_dumps(payload)
        except (TypeError, ValueError, OverflowError):
            sanitized, had_non_finite = sanitize_for_json(payload)
            if had_non_finite:
                LOGGER.warning(
                    "WebSocket payload for client %r contained NaN/Inf values; replaced with null.",
                    selected_client_id,
                )
            return json_text_dumps(sanitized)
    except _BUILD_FAILURE_EXCEPTIONS:
        LOGGER.error(
            "WebSocket payload serialization failed for client %r; sending error payload.",
            selected_client_id,
            exc_info=True,
        )
        return ERROR_PAYLOAD_TEXT
