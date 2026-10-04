"""Async GPS transport-running orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from vibesensor.common.json_types import JsonObject, is_json_object
from vibesensor.speed.gps_transport_lifecycle import TransportLifecycle
from vibesensor.speed.gps_transport_updates import MetricReader, TpvModeReader

if TYPE_CHECKING:
    from vibesensor.speed.gps_transport import GPSTransportState

LOGGER = logging.getLogger(__name__)
_WATCH_ENABLE_PAYLOAD = b'?WATCH={"enable":true,"json":true};\n'
_OUTAGE_SUMMARY_INTERVAL_S = 600.0
"""While GPS stays unavailable, repeat failures log one info summary per interval."""


class _OutageLog:
    """Log GPS outages on state change only, with a periodic summary.

    Without a receiver, gpsd accepts the connection but never sends a fix, so
    every read times out. Logging each retry flooded the journal.
    """

    __slots__ = ("_attempts", "_last_error", "_last_summary_s")

    def __init__(self) -> None:
        self._attempts = 0
        self._last_error: str | None = None
        self._last_summary_s = 0.0

    def failed(self, error: str, retry_in_s: float) -> None:
        self._attempts += 1
        now = time.monotonic()
        if error != self._last_error:
            self._last_error = error
            self._last_summary_s = now
            LOGGER.warning(
                "GPS unavailable (%s); retrying with backoff, further failures are logged "
                "every %.0f min",
                error,
                _OUTAGE_SUMMARY_INTERVAL_S / 60,
            )
        elif now - self._last_summary_s >= _OUTAGE_SUMMARY_INTERVAL_S:
            self._last_summary_s = now
            LOGGER.info(
                "GPS still unavailable after %d attempts (%s); next retry in %gs",
                self._attempts,
                error,
                retry_in_s,
            )
        else:
            LOGGER.debug("GPS retry %d failed (%s); next in %gs", self._attempts, error, retry_in_s)

    def recovered(self) -> None:
        if self._last_error is not None:
            LOGGER.info("GPS data resumed after %d failed attempts", self._attempts)
        self._attempts = 0
        self._last_error = None


class GPSTransportRunner:
    """Own async connect/read/reconnect orchestration for the GPS transport."""

    def __init__(
        self,
        *,
        disabled_poll_s: float,
        reconnect_delay_s: float,
        connect_timeout_s: float,
        read_timeout_s: float,
        reconnect_max_delay_s: float,
    ) -> None:
        self._disabled_poll_s = disabled_poll_s
        self._reconnect_delay_s = reconnect_delay_s
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._reconnect_max_delay_s = reconnect_max_delay_s

    async def run(
        self,
        state: GPSTransportState,
        *,
        host: str,
        port: int,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        lifecycle = TransportLifecycle(
            initial_delay=self._reconnect_delay_s,
            max_delay=self._reconnect_max_delay_s,
        )
        outage = _OutageLog()
        while True:
            if not state.gps_enabled:
                state.set_enabled(False)
                await asyncio.sleep(self._disabled_poll_s)
                continue

            writer: asyncio.StreamWriter | None = None
            writer_closed = False
            retry_delay: float | None = None
            try:
                state.connection_state = "disconnected"
                reader, connected_writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=self._connect_timeout_s,
                )
                writer = connected_writer
                writer.write(_WATCH_ENABLE_PAYLOAD)
                await writer.drain()
                transition = lifecycle.on_connected()
                state._apply_transition_changes(transition.changes)
                retry_delay = await self._read_session(
                    state,
                    reader,
                    lifecycle,
                    outage,
                    tpv_mode=tpv_mode,
                    read_metric=read_metric,
                )
            except asyncio.CancelledError:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                    writer_closed = True
                state.speed_mps = None
                raise
            except (
                OSError,
                TimeoutError,
                ConnectionError,
                EOFError,
                json.JSONDecodeError,
            ) as exc:
                transition = lifecycle.on_connection_error(exc)
                state._apply_transition_changes(transition.changes)
                outage.failed(str(exc) or type(exc).__name__, transition.sleep_before_retry or 0.0)
                LOGGER.debug(
                    "GPS reconnect exception detail",
                    exc_info=True,
                )
                await asyncio.sleep(transition.sleep_before_retry)  # type: ignore[arg-type]
            finally:
                if writer is not None and not writer_closed:
                    writer.close()
                    await writer.wait_closed()
            if retry_delay is not None:
                await asyncio.sleep(retry_delay)

    async def _read_session(
        self,
        state: GPSTransportState,
        reader: asyncio.StreamReader,
        lifecycle: TransportLifecycle,
        outage: _OutageLog,
        *,
        tpv_mode: TpvModeReader | None,
        read_metric: MetricReader | None,
    ) -> float | None:
        """Read until disabled or the peer closes; return the delay before reconnecting.

        The reconnect backoff resets only once a TPV report arrives: gpsd without
        a receiver accepts connections but never sends one.
        """
        while True:
            if not state.gps_enabled:
                state.set_enabled(False)
                return None
            line = await asyncio.wait_for(reader.readline(), timeout=self._read_timeout_s)
            if not line:
                transition = lifecycle.on_stream_disconnected()
                state._apply_transition_changes(transition.changes)
                LOGGER.info(
                    "GPS stream closed by gpsd, reconnecting in %gs",
                    transition.sleep_before_retry,
                )
                return transition.sleep_before_retry
            payload = self._decode_json_line(line)
            if payload is None:
                continue
            if state.ingest_message(payload, tpv_mode=tpv_mode, read_metric=read_metric):
                lifecycle.reset_delay()
                outage.recovered()

    @staticmethod
    def _decode_json_line(line: bytes) -> JsonObject | None:
        try:
            parsed = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            LOGGER.debug("Ignoring malformed GPS JSON line")
            return None
        if not is_json_object(parsed):
            LOGGER.debug("Ignoring non-object GPS JSON line")
            return None
        return parsed
