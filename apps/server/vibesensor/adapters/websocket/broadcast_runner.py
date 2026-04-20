"""Per-tick broadcast runner for the WebSocket hub.

Owns payload orchestration, per-connection send, dead-socket cleanup,
and failure/debug reporting so ``WebSocketHub`` stays focused on
connection lifecycle and tick cadence.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from opentelemetry.trace import SpanKind

from vibesensor.adapters.websocket.connection_tracker import (
    ConnectionTracker,
    WSConnectionSnapshot,
)
from vibesensor.adapters.websocket.payload_orchestrator import PayloadBuildOrchestrator
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.shared.types.payload_types import LiveWsPayload

LOGGER = logging.getLogger(__name__)

__all__ = ["BroadcastRunner"]

_SEND_FAILURE_EXCEPTIONS = (OSError, RuntimeError)


class BroadcastRunner:
    """Executes a single broadcast tick: build payloads, send, clean up."""

    def __init__(
        self,
        tracker: ConnectionTracker,
        *,
        send_timeout_s: float,
        send_error_log_interval_s: float,
    ) -> None:
        self._tracker = tracker
        self._send_timeout_s = send_timeout_s
        self._send_error_log_interval_s = send_error_log_interval_s
        self._last_send_error_log_ts = 0.0

    async def broadcast(
        self,
        payload_builder: Callable[[str | None], LiveWsPayload],
        *,
        capture_debug: bool = False,
    ) -> None:
        """Run one broadcast tick: snapshot → build → send → clean up."""
        conns = await self._tracker.snapshot()
        if not conns:
            return
        with start_span(
            __name__,
            "ws.broadcast.tick",
            kind=SpanKind.INTERNAL,
            attributes={
                "vibesensor.connection_count": len(conns),
                "vibesensor.capture_debug": capture_debug,
            },
        ) as span:
            payloads = PayloadBuildOrchestrator(
                payload_builder,
                capture_debug=capture_debug,
            )
            try:
                await payloads.prepare(conn.selected_client_id for conn in conns)
                sent_selected_client_ids: dict[int, str | None] = {}

                dead_ws = await asyncio.gather(
                    *(
                        self._send_current_conn(conn, payloads, sent_selected_client_ids)
                        for conn in conns
                    ),
                )
                await self._cleanup_dead(dead_ws)
            except Exception as exc:
                mark_span_error(span, exc)
                raise
            span.set_attribute("vibesensor.payload_variant_count", len(payloads.payload_cache))
            span.set_attribute("vibesensor.failed_client_count", len(payloads.failed_client_ids))
            span.set_attribute(
                "vibesensor.removed_connection_count", sum(1 for ws in dead_ws if ws)
            )
            self._log_build_failures(payloads, sent_selected_client_ids)
            self._log_debug(payloads, conns, dead_ws)

    async def _send_conn(
        self,
        conn: WSConnectionSnapshot,
        payload_text: str,
        *,
        selected_client_id: str | None,
    ) -> WSConnectionSnapshot | None:
        """Send *payload_text* to *conn*, return the snapshot on failure."""
        if not await self._tracker.is_snapshot_current(conn):
            return None
        try:
            await asyncio.wait_for(
                conn.websocket.send_text(payload_text),
                timeout=self._send_timeout_s,
            )
            return None
        except _SEND_FAILURE_EXCEPTIONS:
            now = asyncio.get_running_loop().time()
            if (now - self._last_send_error_log_ts) >= self._send_error_log_interval_s:
                self._last_send_error_log_ts = now
                LOGGER.warning(
                    "WebSocket broadcast send failed (selected_client=%r); "
                    "connection will be removed.",
                    selected_client_id,
                    exc_info=True,
                    extra=log_extra(
                        event="ws_broadcast_send_failed",
                        selected_client_id=selected_client_id,
                    ),
                )
            if await self._tracker.mark_snapshot_closing(conn):
                return conn
            return None

    async def _send_current_conn(
        self,
        conn: WSConnectionSnapshot,
        payloads: PayloadBuildOrchestrator,
        sent_selected_client_ids: dict[int, str | None],
    ) -> WSConnectionSnapshot | None:
        """Send a payload built for the connection's current selection."""
        is_current, selected_client_id = await self._tracker.current_selected_client_id(conn)
        if not is_current:
            return None
        payload_text = await payloads.get_or_build_payload_text(selected_client_id)
        still_current, latest_selected_client_id = await self._tracker.current_selected_client_id(
            conn
        )
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

    async def _cleanup_dead(
        self,
        dead_ws: list[WSConnectionSnapshot | None],
    ) -> None:
        for conn in dead_ws:
            if conn is not None:
                with contextlib.suppress(*_SEND_FAILURE_EXCEPTIONS):
                    await conn.websocket.close()
                await self._tracker.remove_snapshot(conn)

    def _log_build_failures(
        self,
        payloads: PayloadBuildOrchestrator,
        sent_selected_client_ids: dict[int, str | None],
    ) -> None:
        if not payloads.failed_client_ids:
            return
        affected = sum(
            1 for cid in sent_selected_client_ids.values() if cid in payloads.failed_client_ids
        )
        LOGGER.error(
            "WebSocket payload build failed for %d client id(s) (%s); "
            "%d connection(s) received error payloads.",
            len(payloads.failed_client_ids),
            ", ".join(repr(cid) for cid in payloads.failed_client_ids),
            affected,
            extra=log_extra(
                event="ws_broadcast_payload_build_failed",
                failed_client_ids=sorted(
                    "None" if cid is None else cid for cid in payloads.failed_client_ids
                ),
                affected_connection_count=affected,
            ),
        )

    def _log_debug(
        self,
        payloads: PayloadBuildOrchestrator,
        conns: list[WSConnectionSnapshot],
        dead_ws: list[WSConnectionSnapshot | None],
    ) -> None:
        if payloads.debug_info is None or not payloads.payload_cache:
            return
        live_count = len(conns) - sum(1 for ws in dead_ws if ws is not None)
        for sel_id, text in payloads.payload_cache.items():
            LOGGER.debug(
                "WS_DEBUG selected=%r size_bytes=%d connections=%d per_client_freq=%s",
                sel_id,
                len(text),
                live_count,
                payloads.debug_info.get(sel_id, False),
            )
