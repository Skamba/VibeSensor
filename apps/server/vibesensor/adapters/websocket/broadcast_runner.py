"""Per-tick broadcast runner for the WebSocket hub.

Owns payload orchestration, per-connection send, dead-socket cleanup,
and failure/debug reporting so ``WebSocketHub`` stays focused on
connection lifecycle and tick cadence.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable

import anyio
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
_DEFAULT_MAX_CONCURRENT_SENDS = 16
_DEFAULT_MAX_SENDS_PER_TICK = 128
_DEFAULT_MAX_CONCURRENT_PAYLOAD_SERIALIZATIONS = 4
_DEFAULT_MAX_PAYLOAD_VARIANTS_PER_TICK = 32


class BroadcastRunner:
    """Executes a single broadcast tick: build payloads, send, clean up."""

    def __init__(
        self,
        tracker: ConnectionTracker,
        *,
        send_timeout_s: float,
        send_error_log_interval_s: float,
        max_concurrent_sends: int = _DEFAULT_MAX_CONCURRENT_SENDS,
        max_sends_per_tick: int = _DEFAULT_MAX_SENDS_PER_TICK,
        max_concurrent_payload_serializations: int = (
            _DEFAULT_MAX_CONCURRENT_PAYLOAD_SERIALIZATIONS
        ),
        max_payload_variants_per_tick: int = _DEFAULT_MAX_PAYLOAD_VARIANTS_PER_TICK,
    ) -> None:
        self._tracker = tracker
        self._send_timeout_s = send_timeout_s
        self._send_error_log_interval_s = send_error_log_interval_s
        self._max_concurrent_sends = max(1, int(max_concurrent_sends))
        self._max_sends_per_tick = max(1, int(max_sends_per_tick))
        self._max_concurrent_payload_serializations = max(
            1,
            int(max_concurrent_payload_serializations),
        )
        self._max_payload_variants_per_tick = max(1, int(max_payload_variants_per_tick))
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
            tick_started = time.monotonic()
            send_conns = conns[: self._max_sends_per_tick]
            skipped_send_count = len(conns) - len(send_conns)
            payloads = PayloadBuildOrchestrator(
                payload_builder,
                capture_debug=capture_debug,
                max_concurrent_serializations=self._max_concurrent_payload_serializations,
                max_payload_variants=self._max_payload_variants_per_tick,
            )
            try:
                await payloads.prepare(conn.selected_client_id for conn in send_conns)
                sent_selected_client_ids: dict[int, str | None] = {}

                dead_ws: list[WSConnectionSnapshot | None] = [None] * len(send_conns)
                for start in range(0, len(send_conns), self._max_concurrent_sends):
                    async with anyio.create_task_group() as task_group:
                        for index, conn in enumerate(
                            send_conns[start : start + self._max_concurrent_sends],
                            start=start,
                        ):
                            task_group.start_soon(
                                self._send_current_conn_into_slot,
                                index,
                                conn,
                                payloads,
                                sent_selected_client_ids,
                                dead_ws,
                            )
                await self._cleanup_dead(dead_ws)
            except Exception as exc:
                mark_span_error(span, exc)
                raise
            span.set_attribute("vibesensor.payload_variant_count", len(payloads.payload_cache))
            span.set_attribute("vibesensor.payload_cache_bytes", payloads.payload_cache_bytes)
            span.set_attribute(
                "vibesensor.payload_serialization_count",
                payloads.serialized_payload_count,
            )
            tick_duration_ms = max(0, int(round((time.monotonic() - tick_started) * 1000)))
            span.set_attribute("vibesensor.tick_duration_ms", tick_duration_ms)
            span.set_attribute("vibesensor.failed_client_count", len(payloads.failed_client_ids))
            span.set_attribute("vibesensor.skipped_send_count", skipped_send_count)
            span.set_attribute(
                "vibesensor.skipped_payload_variant_count",
                len(payloads.skipped_client_ids),
            )
            span.set_attribute(
                "vibesensor.removed_connection_count", sum(1 for ws in dead_ws if ws)
            )
            self._log_backpressure(
                connection_count=len(conns),
                skipped_send_count=skipped_send_count,
                tick_duration_ms=tick_duration_ms,
                payloads=payloads,
            )
            self._log_build_failures(payloads, sent_selected_client_ids)
            self._log_debug(payloads, send_conns, dead_ws)

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
            with anyio.fail_after(self._send_timeout_s):
                await conn.websocket.send_text(payload_text)
            return None
        except (*_SEND_FAILURE_EXCEPTIONS, TimeoutError):
            now = anyio.current_time()
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

    async def _send_current_conn_into_slot(
        self,
        index: int,
        conn: WSConnectionSnapshot,
        payloads: PayloadBuildOrchestrator,
        sent_selected_client_ids: dict[int, str | None],
        dead_ws: list[WSConnectionSnapshot | None],
    ) -> None:
        dead_ws[index] = await self._send_current_conn(conn, payloads, sent_selected_client_ids)

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

    def _log_backpressure(
        self,
        *,
        connection_count: int,
        skipped_send_count: int,
        tick_duration_ms: int,
        payloads: PayloadBuildOrchestrator,
    ) -> None:
        skipped_payload_variant_count = len(payloads.skipped_client_ids)
        if skipped_send_count <= 0 and skipped_payload_variant_count <= 0:
            return
        LOGGER.warning(
            "WebSocket broadcast backpressure skipped sends=%d payload_variants=%d",
            skipped_send_count,
            skipped_payload_variant_count,
            extra=log_extra(
                event="ws_broadcast_backpressure",
                connection_count=connection_count,
                max_sends_per_tick=self._max_sends_per_tick,
                max_concurrent_sends=self._max_concurrent_sends,
                skipped_send_count=skipped_send_count,
                max_payload_variants_per_tick=self._max_payload_variants_per_tick,
                max_concurrent_payload_serializations=(self._max_concurrent_payload_serializations),
                skipped_payload_variant_count=skipped_payload_variant_count,
                payload_cache_bytes=payloads.payload_cache_bytes,
                payload_serialization_count=payloads.serialized_payload_count,
                tick_duration_ms=tick_duration_ms,
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
