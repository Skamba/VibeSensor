"""GPSD transport loop and TPV ingestion state."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from vibesensor.shared.constants import NUMERIC_TYPES
from vibesensor.shared.types.json_types import JsonObject, is_json_object

LOGGER = logging.getLogger(__name__)

_GPS_DISABLED_POLL_S: float = 5.0
"""Sleep interval when GPS is disabled."""

_GPS_RECONNECT_DELAY_S: float = 2.0
"""Delay before reconnecting after a GPS connection loss."""

_GPS_CONNECT_TIMEOUT_S: float = 3.0
_GPS_READ_TIMEOUT_S: float = 3.0
_GPS_RECONNECT_MAX_DELAY_S: float = 15.0
_GPS_MAX_SPEED_MPS: float = 150.0
"""Reject GPS TPV speed samples above this value (≈ 540 km/h) as implausible."""
_GPS_ZERO_DROP_PREV_THRESHOLD_MPS: float = 0.5
_GPS_ZERO_CONFIRM_SAMPLES: int = 3

TpvModeReader = Callable[[JsonObject], int | None]
MetricReader = Callable[[JsonObject, str], float | None]


@dataclass
class GPSTransportState:
    """Mutable GPSD connection state and raw TPV ingestion logic."""

    gps_enabled: bool
    connection_state: str = field(init=False)
    _speed_snapshot: tuple[float | None, float | None] = (None, None)
    last_error: str | None = None
    current_reconnect_delay: float = _GPS_RECONNECT_DELAY_S
    device_info: str | None = None
    last_fix_mode: int | None = None
    last_epx_m: float | None = None
    last_epy_m: float | None = None
    last_epv_m: float | None = None
    _zero_speed_streak: int = 0

    def __post_init__(self) -> None:
        self.connection_state = "disabled" if not self.gps_enabled else "disconnected"

    @property
    def speed_mps(self) -> float | None:
        return self._speed_snapshot[0]

    @speed_mps.setter
    def speed_mps(self, value: float | None) -> None:
        self._speed_snapshot = (value, self._speed_snapshot[1])

    @property
    def last_update_ts(self) -> float | None:
        return self._speed_snapshot[1]

    @staticmethod
    def _read_non_negative_metric(payload: JsonObject, field: str) -> float | None:
        value = payload.get(field)
        if isinstance(value, NUMERIC_TYPES) and not isinstance(value, bool):
            numeric_value = float(value)
            if math.isfinite(numeric_value) and numeric_value >= 0:
                return numeric_value
        return None

    @staticmethod
    def _tpv_mode(payload: JsonObject) -> int | None:
        mode = payload.get("mode")
        if isinstance(mode, int) and not isinstance(mode, bool):
            return mode
        return None

    def _accept_speed_sample(self, speed_mps: float) -> bool:
        if speed_mps == 0.0:
            prev_speed = self._speed_snapshot[0]
            if (
                isinstance(prev_speed, NUMERIC_TYPES)
                and prev_speed > _GPS_ZERO_DROP_PREV_THRESHOLD_MPS
            ):
                self._zero_speed_streak += 1
                return self._zero_speed_streak >= _GPS_ZERO_CONFIRM_SAMPLES
        self._zero_speed_streak = 0
        return True

    def _reset_fix_metadata(self) -> None:
        self.last_fix_mode = None
        self.last_epx_m = None
        self.last_epy_m = None
        self.last_epv_m = None
        self._zero_speed_streak = 0
        self._speed_snapshot = (None, None)
        self.device_info = None

    def ingest_message(
        self,
        payload: JsonObject,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        payload_class = payload.get("class")
        if payload_class == "VERSION":
            revision = payload.get("rev")
            if isinstance(revision, str):
                self.device_info = f"gpsd {revision}"
            return
        if payload_class != "TPV":
            return
        self.ingest_tpv(payload, tpv_mode=tpv_mode, read_metric=read_metric)

    def ingest_tpv(
        self,
        payload: JsonObject,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        read_mode = self._tpv_mode if tpv_mode is None else tpv_mode
        metric_reader = self._read_non_negative_metric if read_metric is None else read_metric

        mode = read_mode(payload)
        self.last_fix_mode = mode
        self.last_epx_m = metric_reader(payload, "epx")
        self.last_epy_m = metric_reader(payload, "epy")
        self.last_epv_m = metric_reader(payload, "epv")

        speed = payload.get("speed")
        if (
            isinstance(mode, int)
            and mode >= 2
            and isinstance(speed, NUMERIC_TYPES)
            and not isinstance(speed, bool)
        ):
            speed_f = float(speed)
            if math.isfinite(speed_f) and 0 <= speed_f <= _GPS_MAX_SPEED_MPS:
                if self._accept_speed_sample(speed_f):
                    self._speed_snapshot = (speed_f, time.monotonic())
            else:
                self._zero_speed_streak = 0
        else:
            self._zero_speed_streak = 0

        device = payload.get("device")
        if isinstance(device, str) and device:
            self.device_info = device

    async def run(
        self,
        host: str = "127.0.0.1",
        port: int = 2947,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        loads = json.loads
        reconnect_delay = _GPS_RECONNECT_DELAY_S
        while True:
            if not self.gps_enabled:
                self.speed_mps = None
                self.connection_state = "disabled"
                await asyncio.sleep(_GPS_DISABLED_POLL_S)
                continue

            writer: asyncio.StreamWriter | None = None
            writer_closed = False
            try:
                self.connection_state = "disconnected"
                reader, connected_writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=_GPS_CONNECT_TIMEOUT_S,
                )
                writer = connected_writer
                writer.write(b'?WATCH={"enable":true,"json":true};\n')
                await writer.drain()
                self.connection_state = "connected"
                self.last_error = None
                self.current_reconnect_delay = _GPS_RECONNECT_DELAY_S
                reconnect_delay = _GPS_RECONNECT_DELAY_S
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=_GPS_READ_TIMEOUT_S)
                    if not line:
                        self.speed_mps = None
                        self.connection_state = "disconnected"
                        self._reset_fix_metadata()
                        break
                    try:
                        parsed = loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        LOGGER.debug("Ignoring malformed GPS JSON line")
                        continue
                    if not is_json_object(parsed):
                        LOGGER.debug("Ignoring non-object GPS JSON line")
                        continue
                    self.ingest_message(parsed, tpv_mode=tpv_mode, read_metric=read_metric)
                reconnect_delay = _GPS_RECONNECT_DELAY_S
            except asyncio.CancelledError:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                    writer_closed = True
                self.speed_mps = None
                raise
            except (
                OSError,
                TimeoutError,
                ConnectionError,
                EOFError,
                json.JSONDecodeError,
            ) as exc:
                self.speed_mps = None
                self.connection_state = "disconnected"
                self._reset_fix_metadata()
                self.last_error = str(exc) or type(exc).__name__
                self.current_reconnect_delay = reconnect_delay
                LOGGER.warning(
                    "GPS connection lost, retrying in %gs: %s",
                    reconnect_delay,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(_GPS_RECONNECT_MAX_DELAY_S, reconnect_delay * 2.0)
            finally:
                if writer is not None and not writer_closed:
                    writer.close()
                    await writer.wait_closed()
