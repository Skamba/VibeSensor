"""Async GPS transport-running orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Protocol

from vibesensor.adapters.gps.gps_transport_updates import MetricReader, TpvModeReader
from vibesensor.adapters.gps.transport_lifecycle import TransportLifecycle
from vibesensor.shared.types.json_types import JsonObject, is_json_object

LOGGER = logging.getLogger(__name__)
_WATCH_ENABLE_PAYLOAD = b'?WATCH={"enable":true,"json":true};\n'


class GPSTransportRuntimeState(Protocol):
    """Minimal state seam required by the GPS transport runner."""

    gps_enabled: bool
    connection_state: str
    speed_mps: float | None

    def set_enabled(self, enabled: bool) -> None: ...

    def _apply_transition_changes(self, changes: dict[str, object]) -> None: ...

    def ingest_message(
        self,
        payload: JsonObject,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None: ...


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
        state: GPSTransportRuntimeState,
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
        while True:
            if not state.gps_enabled:
                state.set_enabled(False)
                await asyncio.sleep(self._disabled_poll_s)
                continue

            writer: asyncio.StreamWriter | None = None
            writer_closed = False
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
                await self._read_session(
                    state,
                    reader,
                    lifecycle,
                    tpv_mode=tpv_mode,
                    read_metric=read_metric,
                )
                lifecycle.reset_delay()
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
                LOGGER.warning(
                    "GPS connection lost, retrying in %gs: %s",
                    transition.sleep_before_retry,
                    str(exc) or type(exc).__name__,
                )
                LOGGER.debug(
                    "GPS reconnect exception detail",
                    exc_info=True,
                )
                await asyncio.sleep(transition.sleep_before_retry)  # type: ignore[arg-type]
            finally:
                if writer is not None and not writer_closed:
                    writer.close()
                    await writer.wait_closed()

    async def _read_session(
        self,
        state: GPSTransportRuntimeState,
        reader: asyncio.StreamReader,
        lifecycle: TransportLifecycle,
        *,
        tpv_mode: TpvModeReader | None,
        read_metric: MetricReader | None,
    ) -> None:
        while True:
            if not state.gps_enabled:
                state.set_enabled(False)
                break
            line = await asyncio.wait_for(reader.readline(), timeout=self._read_timeout_s)
            if not line:
                transition = lifecycle.on_stream_disconnected()
                state._apply_transition_changes(transition.changes)
                break
            payload = self._decode_json_line(line)
            if payload is None:
                continue
            state.ingest_message(payload, tpv_mode=tpv_mode, read_metric=read_metric)

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
