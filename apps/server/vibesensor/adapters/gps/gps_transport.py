"""GPSD transport loop and TPV ingestion state."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, cast

from vibesensor.adapters.gps.gpsd_message_handler import (
    GpsdVersionInfo,
    NormalizedTpvData,
    classify_gpsd_message,
    read_non_negative_metric,
    read_tpv_mode,
)
from vibesensor.adapters.gps.speed_validation import (
    DEFAULT_SPEED_VALIDATION_CONFIG,
    evaluate_speed_sample,
    is_speed_plausible,
)
from vibesensor.adapters.gps.transport_lifecycle import (
    GPS_CONNECT_TIMEOUT_S,
    GPS_DISABLED_POLL_S,
    GPS_READ_TIMEOUT_S,
    GPS_RECONNECT_DELAY_S,
    GPS_RECONNECT_MAX_DELAY_S,
    TransportLifecycle,
)
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.types.json_types import JsonObject, is_json_object

LOGGER = logging.getLogger(__name__)

# Backward-compatible aliases for constants that consumers import from here.
_GPS_DISABLED_POLL_S: float = GPS_DISABLED_POLL_S
_GPS_RECONNECT_DELAY_S: float = GPS_RECONNECT_DELAY_S
_GPS_CONNECT_TIMEOUT_S: float = GPS_CONNECT_TIMEOUT_S
_GPS_READ_TIMEOUT_S: float = GPS_READ_TIMEOUT_S
_GPS_RECONNECT_MAX_DELAY_S: float = GPS_RECONNECT_MAX_DELAY_S

# Re-export for consumers that import from this module.
_GPS_MAX_SPEED_MPS: float = DEFAULT_SPEED_VALIDATION_CONFIG.max_speed_mps

TpvModeReader = Callable[[JsonObject], int | None]
MetricReader = Callable[[JsonObject, str], float | None]


@dataclass(frozen=True, slots=True)
class GPSTransportSnapshot:
    """Immutable transport snapshot captured by GPS readers."""

    gps_enabled: bool
    connection_state: str
    speed_snapshot: tuple[float | None, float | None] = (None, None)
    last_error: str | None = None
    current_reconnect_delay: float = _GPS_RECONNECT_DELAY_S
    device_info: str | None = None
    last_fix_mode: int | None = None
    last_epx_m: float | None = None
    last_epy_m: float | None = None
    last_epv_m: float | None = None
    zero_speed_streak: int = 0


class GPSTransportState:
    """Owns GPS transport state as immutable snapshots atomically swapped by writers."""

    def __init__(self, gps_enabled: bool):
        self._snapshot = GPSTransportSnapshot(
            gps_enabled=bool(gps_enabled),
            connection_state="disabled" if not gps_enabled else "disconnected",
        )

    def snapshot(self) -> GPSTransportSnapshot:
        return self._snapshot

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GPSTransportState) and self._snapshot == other._snapshot

    def _replace_snapshot(self, **changes: object) -> None:
        self._snapshot = replace(self._snapshot, **cast(dict[str, Any], changes))

    @staticmethod
    def _normalize_optional_float(value: object) -> float | None:
        if value is None or isinstance(value, bool) or not isinstance(value, NUMERIC_TYPES):
            return None
        numeric_value = float(value)
        return numeric_value if math.isfinite(numeric_value) else None

    @staticmethod
    def _normalize_speed_snapshot(
        value: tuple[float | None, float | None],
    ) -> tuple[float | None, float | None]:
        speed, timestamp = value
        return (
            GPSTransportState._normalize_optional_float(speed),
            GPSTransportState._normalize_optional_float(timestamp),
        )

    @staticmethod
    def _evaluate_speed_sample(
        snapshot: GPSTransportSnapshot,
        speed_mps: float,
    ) -> tuple[bool, int]:
        verdict = evaluate_speed_sample(
            speed_mps,
            snapshot.speed_snapshot[0],
            snapshot.zero_speed_streak,
        )
        return verdict.accepted, verdict.zero_speed_streak

    def _mark_connected(self) -> None:
        self._replace_snapshot(
            **TransportLifecycle().on_connected().changes,
        )

    def _mark_stream_disconnected(self) -> None:
        self._replace_snapshot(
            **TransportLifecycle().on_stream_disconnected().changes,
        )

    def _mark_connection_error(self, exc: BaseException, reconnect_delay: float) -> None:
        transition = TransportLifecycle().on_connection_error(exc)
        # Override the delay from the caller's tracked value.
        self._replace_snapshot(
            **{**transition.changes, "current_reconnect_delay": reconnect_delay},
        )

    def set_enabled(self, enabled: bool) -> None:
        snapshot = self._snapshot
        if not enabled:
            self._snapshot = replace(
                snapshot,
                gps_enabled=False,
                connection_state="disabled",
                speed_snapshot=(None, None),
                zero_speed_streak=0,
            )
            return
        if snapshot.connection_state == "disabled":
            self._snapshot = replace(
                snapshot,
                gps_enabled=True,
                connection_state="disconnected",
            )
            return
        self._snapshot = replace(snapshot, gps_enabled=True)

    @property
    def gps_enabled(self) -> bool:
        return self._snapshot.gps_enabled

    @gps_enabled.setter
    def gps_enabled(self, value: bool) -> None:
        self.set_enabled(bool(value))

    @property
    def connection_state(self) -> str:
        return self._snapshot.connection_state

    @connection_state.setter
    def connection_state(self, value: str) -> None:
        self._replace_snapshot(connection_state=str(value))

    @property
    def speed_mps(self) -> float | None:
        return self._snapshot.speed_snapshot[0]

    @speed_mps.setter
    def speed_mps(self, value: float | None) -> None:
        if value is None or isinstance(value, bool) or not isinstance(value, NUMERIC_TYPES):
            self._replace_snapshot(speed_snapshot=(None, None))
            return
        speed_f = float(value)
        if not math.isfinite(speed_f):
            self._replace_snapshot(speed_snapshot=(None, None))
            return
        self._replace_snapshot(speed_snapshot=(speed_f, time.monotonic()))

    @property
    def _speed_snapshot(self) -> tuple[float | None, float | None]:
        return self._snapshot.speed_snapshot

    @_speed_snapshot.setter
    def _speed_snapshot(self, value: tuple[float | None, float | None]) -> None:
        self._replace_snapshot(speed_snapshot=self._normalize_speed_snapshot(value))

    @property
    def last_update_ts(self) -> float | None:
        return self._snapshot.speed_snapshot[1]

    @property
    def last_error(self) -> str | None:
        return self._snapshot.last_error

    @last_error.setter
    def last_error(self, value: str | None) -> None:
        self._replace_snapshot(last_error=(str(value) if value is not None else None))

    @property
    def current_reconnect_delay(self) -> float:
        return self._snapshot.current_reconnect_delay

    @current_reconnect_delay.setter
    def current_reconnect_delay(self, value: float) -> None:
        self._replace_snapshot(current_reconnect_delay=float(value))

    @property
    def device_info(self) -> str | None:
        return self._snapshot.device_info

    @device_info.setter
    def device_info(self, value: str | None) -> None:
        self._replace_snapshot(device_info=(str(value) if value is not None else None))

    @property
    def last_fix_mode(self) -> int | None:
        return self._snapshot.last_fix_mode

    @last_fix_mode.setter
    def last_fix_mode(self, value: int | None) -> None:
        self._replace_snapshot(
            last_fix_mode=value if isinstance(value, int) and not isinstance(value, bool) else None
        )

    @property
    def last_epx_m(self) -> float | None:
        return self._snapshot.last_epx_m

    @last_epx_m.setter
    def last_epx_m(self, value: float | None) -> None:
        self._replace_snapshot(last_epx_m=self._normalize_optional_float(value))

    @property
    def last_epy_m(self) -> float | None:
        return self._snapshot.last_epy_m

    @last_epy_m.setter
    def last_epy_m(self, value: float | None) -> None:
        self._replace_snapshot(last_epy_m=self._normalize_optional_float(value))

    @property
    def last_epv_m(self) -> float | None:
        return self._snapshot.last_epv_m

    @last_epv_m.setter
    def last_epv_m(self, value: float | None) -> None:
        self._replace_snapshot(last_epv_m=self._normalize_optional_float(value))

    @property
    def _zero_speed_streak(self) -> int:
        return self._snapshot.zero_speed_streak

    @_zero_speed_streak.setter
    def _zero_speed_streak(self, value: int) -> None:
        self._replace_snapshot(zero_speed_streak=max(0, int(value)))

    @staticmethod
    def _read_non_negative_metric(payload: JsonObject, field: str) -> float | None:
        return read_non_negative_metric(payload, field)

    @staticmethod
    def _tpv_mode(payload: JsonObject) -> int | None:
        return read_tpv_mode(payload)

    def _accept_speed_sample(self, speed_mps: float) -> bool:
        accepted, zero_speed_streak = self._evaluate_speed_sample(self._snapshot, speed_mps)
        self._replace_snapshot(zero_speed_streak=zero_speed_streak)
        return accepted

    def _reset_fix_metadata(self) -> None:
        self._replace_snapshot(
            last_fix_mode=None,
            last_epx_m=None,
            last_epy_m=None,
            last_epv_m=None,
            zero_speed_streak=0,
            speed_snapshot=(None, None),
            device_info=None,
        )

    def ingest_message(
        self,
        payload: JsonObject,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        message = classify_gpsd_message(payload)
        if message is None:
            return
        if isinstance(message, GpsdVersionInfo):
            self._replace_snapshot(device_info=f"gpsd {message.revision}")
            return
        self._apply_tpv(message)

    def _apply_tpv(self, tpv: NormalizedTpvData) -> None:
        """Apply normalized TPV data to the transport snapshot."""
        snapshot = self._snapshot
        speed_snapshot = snapshot.speed_snapshot
        zero_speed_streak = snapshot.zero_speed_streak

        if isinstance(tpv.mode, int) and tpv.mode >= 2 and tpv.speed is not None:
            if is_speed_plausible(tpv.speed):
                accepted, zero_speed_streak = self._evaluate_speed_sample(snapshot, tpv.speed)
                if accepted:
                    speed_snapshot = (tpv.speed, time.monotonic())
            else:
                zero_speed_streak = 0
        else:
            zero_speed_streak = 0

        device_info = tpv.device if tpv.device else snapshot.device_info
        self._snapshot = replace(
            snapshot,
            last_fix_mode=tpv.mode,
            last_epx_m=tpv.epx,
            last_epy_m=tpv.epy,
            last_epv_m=tpv.epv,
            speed_snapshot=speed_snapshot,
            zero_speed_streak=zero_speed_streak,
            device_info=device_info,
        )

    def ingest_tpv(
        self,
        payload: JsonObject,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        read_mode = self._tpv_mode if tpv_mode is None else tpv_mode
        metric_reader = self._read_non_negative_metric if read_metric is None else read_metric
        snapshot = self._snapshot

        mode = read_mode(payload)
        speed_snapshot = snapshot.speed_snapshot
        zero_speed_streak = snapshot.zero_speed_streak

        speed = payload.get("speed")
        if (
            isinstance(mode, int)
            and mode >= 2
            and isinstance(speed, NUMERIC_TYPES)
            and not isinstance(speed, bool)
        ):
            speed_f = float(speed)
            if is_speed_plausible(speed_f):
                accepted, zero_speed_streak = self._evaluate_speed_sample(snapshot, speed_f)
                if accepted:
                    speed_snapshot = (speed_f, time.monotonic())
            else:
                zero_speed_streak = 0
        else:
            zero_speed_streak = 0

        device = payload.get("device")
        device_info = device if isinstance(device, str) and device else snapshot.device_info
        self._snapshot = replace(
            snapshot,
            last_fix_mode=mode if isinstance(mode, int) else None,
            last_epx_m=metric_reader(payload, "epx"),
            last_epy_m=metric_reader(payload, "epy"),
            last_epv_m=metric_reader(payload, "epv"),
            speed_snapshot=speed_snapshot,
            zero_speed_streak=zero_speed_streak,
            device_info=device_info,
        )

    async def run(
        self,
        host: str = "127.0.0.1",
        port: int = 2947,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        loads = json.loads
        lifecycle = TransportLifecycle(
            initial_delay=_GPS_RECONNECT_DELAY_S,
            max_delay=_GPS_RECONNECT_MAX_DELAY_S,
        )
        while True:
            if not self.gps_enabled:
                self.set_enabled(False)
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
                transition = lifecycle.on_connected()
                self._replace_snapshot(**transition.changes)
                while True:
                    if not self.gps_enabled:
                        self.set_enabled(False)
                        break
                    line = await asyncio.wait_for(reader.readline(), timeout=_GPS_READ_TIMEOUT_S)
                    if not line:
                        transition = lifecycle.on_stream_disconnected()
                        self._replace_snapshot(**transition.changes)
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
                lifecycle.reset_delay()
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
                transition = lifecycle.on_connection_error(exc)
                self._replace_snapshot(**transition.changes)
                LOGGER.warning(
                    "GPS connection lost, retrying in %gs: %s",
                    transition.sleep_before_retry,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(transition.sleep_before_retry)  # type: ignore[arg-type]
            finally:
                if writer is not None and not writer_closed:
                    writer.close()
                    await writer.wait_closed()
