"""GPSD transport loop and TPV ingestion state."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, cast

from vibesensor.adapters.gps import gps_transport_updates as _transport_updates
from vibesensor.adapters.gps import transport_lifecycle as _transport_lifecycle
from vibesensor.adapters.gps.gps_transport_runner import GPSTransportRunner
from vibesensor.adapters.gps.gpsd_message_handler import GpsdVersionInfo, NormalizedTpvData
from vibesensor.shared.timed_observation import TimedScalarObservation, append_timed_observation
from vibesensor.shared.types.json_types import JsonObject

TpvModeReader = _transport_updates.TpvModeReader
MetricReader = _transport_updates.MetricReader


@dataclass(frozen=True, slots=True)
class GPSTransportSnapshot:
    """Immutable transport snapshot captured by GPS readers."""

    gps_enabled: bool
    connection_state: str
    speed_snapshot: tuple[float | None, float | None] = (None, None)
    speed_history: tuple[TimedScalarObservation, ...] = ()
    device_info: str | None = None
    last_fix_mode: int | None = None
    last_epx_m: float | None = None
    last_epy_m: float | None = None
    last_epv_m: float | None = None
    zero_speed_streak: int = 0


@dataclass(frozen=True, slots=True)
class GPSTransportLifecycleState:
    """Reconnect/backoff state captured alongside the observational transport snapshot."""

    last_error: str | None = None
    current_reconnect_delay: float = _transport_lifecycle.GPS_RECONNECT_DELAY_S


@dataclass(frozen=True, slots=True)
class GPSTransportCapturedState:
    """Atomic GPS state handoff containing both observational and lifecycle snapshots."""

    transport: GPSTransportSnapshot
    lifecycle: GPSTransportLifecycleState


_LIFECYCLE_FIELD_NAMES = frozenset({"last_error", "current_reconnect_delay"})


class GPSTransportState:
    """Owns GPS transport state as immutable snapshots atomically swapped by writers."""

    def __init__(self, gps_enabled: bool):
        self._state = GPSTransportCapturedState(
            transport=GPSTransportSnapshot(
                gps_enabled=bool(gps_enabled),
                connection_state="disabled" if not gps_enabled else "disconnected",
            ),
            lifecycle=GPSTransportLifecycleState(),
        )

    def snapshot(self) -> GPSTransportSnapshot:
        return self._state.transport

    def lifecycle_snapshot(self) -> GPSTransportLifecycleState:
        return self._state.lifecycle

    def captured_state(self) -> GPSTransportCapturedState:
        return self._state

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GPSTransportState) and self._state == other._state

    def _replace_transport(self, **changes: object) -> None:
        self._state = replace(
            self._state,
            transport=replace(self._state.transport, **cast(dict[str, Any], changes)),
        )

    def _replace_lifecycle(self, **changes: object) -> None:
        self._state = replace(
            self._state,
            lifecycle=replace(self._state.lifecycle, **cast(dict[str, Any], changes)),
        )

    def _replace_captured_state(
        self,
        *,
        transport_changes: dict[str, object] | None = None,
        lifecycle_changes: dict[str, object] | None = None,
    ) -> None:
        self._state = GPSTransportCapturedState(
            transport=(
                self._state.transport
                if transport_changes is None
                else replace(self._state.transport, **cast(dict[str, Any], transport_changes))
            ),
            lifecycle=(
                self._state.lifecycle
                if lifecycle_changes is None
                else replace(self._state.lifecycle, **cast(dict[str, Any], lifecycle_changes))
            ),
        )

    def _apply_transition_changes(self, changes: dict[str, object]) -> None:
        transport_changes = {k: v for k, v in changes.items() if k not in _LIFECYCLE_FIELD_NAMES}
        lifecycle_changes = {k: v for k, v in changes.items() if k in _LIFECYCLE_FIELD_NAMES}
        self._replace_captured_state(
            transport_changes=transport_changes or None,
            lifecycle_changes=lifecycle_changes or None,
        )

    def set_enabled(self, enabled: bool) -> None:
        snapshot = self._state.transport
        if not enabled:
            self._replace_transport(
                gps_enabled=False,
                connection_state="disabled",
                speed_snapshot=(None, None),
                zero_speed_streak=0,
            )
            return
        if snapshot.connection_state == "disabled":
            self._replace_transport(
                gps_enabled=True,
                connection_state="disconnected",
            )
            return
        self._replace_transport(gps_enabled=True)

    @property
    def gps_enabled(self) -> bool:
        return self._state.transport.gps_enabled

    @gps_enabled.setter
    def gps_enabled(self, value: bool) -> None:
        self.set_enabled(bool(value))

    @property
    def connection_state(self) -> str:
        return self._state.transport.connection_state

    @connection_state.setter
    def connection_state(self, value: str) -> None:
        self._replace_transport(connection_state=str(value))

    @property
    def speed_mps(self) -> float | None:
        return self._state.transport.speed_snapshot[0]

    @speed_mps.setter
    def speed_mps(self, value: float | None) -> None:
        speed_f = _transport_updates.normalize_optional_float(value)
        if speed_f is None:
            self._replace_transport(speed_snapshot=(None, None))
            return
        now = time.monotonic()
        history = append_timed_observation(
            self._state.transport.speed_history,
            value=speed_f,
            monotonic_s=now,
            now_s=now,
        )
        self._replace_transport(speed_snapshot=(speed_f, now), speed_history=history)

    @property
    def _speed_snapshot(self) -> tuple[float | None, float | None]:
        return self._state.transport.speed_snapshot

    @_speed_snapshot.setter
    def _speed_snapshot(self, value: tuple[float | None, float | None]) -> None:
        normalized = _transport_updates.normalize_speed_snapshot(value)
        speed_value, timestamp = normalized
        history = append_timed_observation(
            self._state.transport.speed_history,
            value=speed_value,
            monotonic_s=timestamp,
            now_s=time.monotonic(),
        )
        self._replace_transport(speed_snapshot=normalized, speed_history=history)

    @property
    def last_update_ts(self) -> float | None:
        return self._state.transport.speed_snapshot[1]

    @property
    def last_error(self) -> str | None:
        return self._state.lifecycle.last_error

    @last_error.setter
    def last_error(self, value: str | None) -> None:
        self._replace_lifecycle(last_error=(str(value) if value is not None else None))

    @property
    def current_reconnect_delay(self) -> float:
        return self._state.lifecycle.current_reconnect_delay

    @current_reconnect_delay.setter
    def current_reconnect_delay(self, value: float) -> None:
        self._replace_lifecycle(current_reconnect_delay=float(value))

    @property
    def device_info(self) -> str | None:
        return self._state.transport.device_info

    @device_info.setter
    def device_info(self, value: str | None) -> None:
        self._replace_transport(device_info=(str(value) if value is not None else None))

    @property
    def last_fix_mode(self) -> int | None:
        return self._state.transport.last_fix_mode

    @last_fix_mode.setter
    def last_fix_mode(self, value: int | None) -> None:
        self._replace_transport(
            last_fix_mode=value if isinstance(value, int) and not isinstance(value, bool) else None
        )

    @property
    def last_epx_m(self) -> float | None:
        return self._state.transport.last_epx_m

    @last_epx_m.setter
    def last_epx_m(self, value: float | None) -> None:
        self._replace_transport(last_epx_m=_transport_updates.normalize_optional_float(value))

    @property
    def last_epy_m(self) -> float | None:
        return self._state.transport.last_epy_m

    @last_epy_m.setter
    def last_epy_m(self, value: float | None) -> None:
        self._replace_transport(last_epy_m=_transport_updates.normalize_optional_float(value))

    @property
    def last_epv_m(self) -> float | None:
        return self._state.transport.last_epv_m

    @last_epv_m.setter
    def last_epv_m(self, value: float | None) -> None:
        self._replace_transport(last_epv_m=_transport_updates.normalize_optional_float(value))

    @property
    def _zero_speed_streak(self) -> int:
        return self._state.transport.zero_speed_streak

    @_zero_speed_streak.setter
    def _zero_speed_streak(self, value: int) -> None:
        self._replace_transport(zero_speed_streak=max(0, int(value)))

    def _accept_speed_sample(self, speed_mps: float) -> bool:
        return _transport_updates.accept_speed_sample(self, speed_mps)

    def _reset_fix_metadata(self) -> None:
        _transport_updates.reset_fix_metadata(self)

    def ingest_message(
        self,
        payload: JsonObject,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        message = _transport_updates.classify_transport_message(
            payload,
            tpv_mode=tpv_mode,
            read_metric=read_metric,
        )
        if message is None:
            return
        if isinstance(message, GpsdVersionInfo):
            self._replace_transport(device_info=f"gpsd {message.revision}")
            return
        self._apply_tpv(message)

    def _apply_tpv(self, tpv: NormalizedTpvData) -> None:
        _transport_updates.apply_tpv(
            self,
            tpv,
            monotonic=time.monotonic,
        )

    def ingest_tpv(
        self,
        payload: JsonObject,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        self._apply_tpv(
            _transport_updates.normalize_tpv_payload(
                payload,
                tpv_mode=tpv_mode,
                read_metric=read_metric,
            )
        )

    async def run(
        self,
        host: str = "127.0.0.1",
        port: int = 2947,
        *,
        tpv_mode: TpvModeReader | None = None,
        read_metric: MetricReader | None = None,
    ) -> None:
        runner = GPSTransportRunner(
            disabled_poll_s=_transport_lifecycle.GPS_DISABLED_POLL_S,
            reconnect_delay_s=_transport_lifecycle.GPS_RECONNECT_DELAY_S,
            connect_timeout_s=_transport_lifecycle.GPS_CONNECT_TIMEOUT_S,
            read_timeout_s=_transport_lifecycle.GPS_READ_TIMEOUT_S,
            reconnect_max_delay_s=_transport_lifecycle.GPS_RECONNECT_MAX_DELAY_S,
        )
        await runner.run(
            self,
            host=host,
            port=port,
            tpv_mode=tpv_mode,
            read_metric=read_metric,
        )
