"""Bluetooth OBD live-speed runtime monitor."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from threading import RLock

from vibesensor.adapters.gps.speed_resolution import SpeedResolution, SpeedResolutionPolicy
from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.elm327 import (
    Elm327Session,
    ObdTransportError,
    elm_response_has_no_data,
    parse_pid_010c_rpm,
    parse_pid_010d_speed_kmh,
)
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.domain import SpeedSourceKind
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import KMH_TO_MPS, MPS_TO_KMH

__all__ = ["OBDSpeedMonitor"]

_INITIAL_RECONNECT_DELAY_S = 1.0
_MAX_RECONNECT_DELAY_S = 30.0
_IDLE_POLL_S = 1.0
_DEFAULT_POLL_INTERVAL_S = 0.75
_ADAPTIVE_POLL_INTERVALS_S = (0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75)
_MIN_REQUEST_TIMEOUT_S = 0.2
_MAX_RPM_REQUEST_TIMEOUT_S = 2.0
_MAX_SPEED_REQUEST_TIMEOUT_S = 0.75
_SPEED_COMPANION_INTERVAL_MULTIPLIER = 4.0
_MIN_SPEED_COMPANION_INTERVAL_S = 0.5
_MAX_SPEED_COMPANION_INTERVAL_S = 1.5
_REQUEST_RTT_EMA_WEIGHT = 0.25
_RPM_INTERVAL_EMA_WEIGHT = 0.25
_STABLE_POLLS_TO_SPEED_UP = 6
_RPM_STALE_TIMEOUT_S = 2.0
_FATAL_TRANSPORT_MARKERS = (
    "closed the rfcomm socket",
    "session is not connected",
    "bad file descriptor",
    "broken pipe",
    "connection reset",
    "host is down",
)


def _normalized_poll_interval_s(value: float) -> float:
    return max(0.2, float(value))


def _adaptive_interval_steps(max_interval_s: float) -> tuple[float, ...]:
    normalized = _normalized_poll_interval_s(max_interval_s)
    steps = tuple(step for step in _ADAPTIVE_POLL_INTERVALS_S if step <= normalized)
    if not steps:
        return (normalized,)
    if steps[-1] != normalized:
        return (*steps, normalized)
    return steps


def _update_ema(current: float | None, sample: float, *, weight: float) -> float:
    return sample if current is None else ((1.0 - weight) * current) + (weight * sample)


def _poll_error_is_timeout(error: str) -> bool:
    return "timed out" in error.lower()


def _poll_error_is_fatal_transport(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in _FATAL_TRANSPORT_MARKERS)


@dataclass(frozen=True, slots=True)
class _PidPollResult:
    value: float | None
    raw_response: str | None
    error: str | None
    duration_s: float | None
    timed_out: bool
    no_data: bool
    executed: bool
    started_at_s: float | None = None
    fatal_transport: bool = False

    @classmethod
    def skipped(cls) -> _PidPollResult:
        return cls(
            value=None,
            raw_response=None,
            error=None,
            duration_s=None,
            timed_out=False,
            no_data=False,
            executed=False,
        )


@dataclass(frozen=True, slots=True)
class _PollResult:
    rpm: _PidPollResult
    speed: _PidPollResult

    @property
    def raw_response(self) -> str | None:
        raw_parts = [part for part in (self.rpm.raw_response, self.speed.raw_response) if part]
        return " | ".join(raw_parts) if raw_parts else None

    @property
    def connection_lost(self) -> bool:
        return self.rpm.fatal_transport or self.speed.fatal_transport


SessionFactory = Callable[[], Elm327Session]
MonotonicFn = Callable[[], float]


class OBDSpeedMonitor:
    """Manage Bluetooth RFCOMM polling plus stale/fallback resolution for OBD speed."""

    __slots__ = (
        "_adaptive_interval_steps",
        "_admin_client",
        "_avg_request_rtt_s",
        "_configured_device_mac",
        "_configured_device_name",
        "_connection_state",
        "_current_reconnect_delay",
        "_device_connected",
        "_device_mac",
        "_device_name",
        "_effective_rpm_interval_s",
        "_engine_rpm",
        "_engine_rpm_ts",
        "_error_count",
        "_last_error",
        "_last_raw_response",
        "_last_rpm_poll_started_at",
        "_lock",
        "_monotonic",
        "_paired",
        "_policy",
        "_poll_interval_s",
        "_rfcomm_channel",
        "_rpm_interval_index",
        "_rpm_next_poll_at",
        "_rpm_stable_poll_count",
        "_selected_source",
        "_session_factory",
        "_speed_degraded",
        "_speed_next_poll_at",
        "_speed_snapshot",
        "_timeout_count",
        "_trusted",
    )

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient | None = None,
        session_factory: SessionFactory | None = None,
        monotonic: MonotonicFn = time.monotonic,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._admin_client = ObdAdminClient() if admin_client is None else admin_client
        self._session_factory = Elm327Session if session_factory is None else session_factory
        self._monotonic = monotonic
        self._poll_interval_s = _normalized_poll_interval_s(poll_interval_s)
        self._adaptive_interval_steps = _adaptive_interval_steps(self._poll_interval_s)
        self._policy = SpeedResolutionPolicy(manual_source_selected=False)
        self._lock = RLock()
        self._selected_source = SpeedSourceKind.GPS
        self._configured_device_mac: str | None = None
        self._configured_device_name: str | None = None
        self._connection_state = "idle"
        self._device_mac: str | None = None
        self._device_name: str | None = None
        self._paired = False
        self._trusted = False
        self._device_connected = False
        self._rfcomm_channel: int | None = None
        self._speed_snapshot: tuple[float | None, float | None] = (None, None)
        self._engine_rpm: float | None = None
        self._engine_rpm_ts: float | None = None
        self._last_error: str | None = None
        self._last_raw_response: str | None = None
        self._current_reconnect_delay = _INITIAL_RECONNECT_DELAY_S
        self._avg_request_rtt_s: float | None = None
        self._effective_rpm_interval_s: float | None = None
        self._last_rpm_poll_started_at: float | None = None
        self._rpm_interval_index = 0
        self._rpm_next_poll_at: float | None = None
        self._rpm_stable_poll_count = 0
        self._speed_degraded = False
        self._speed_next_poll_at: float | None = None
        self._timeout_count = 0
        self._error_count = 0

    @property
    def speed_mps(self) -> float | None:
        with self._lock:
            return self._speed_snapshot[0]

    @property
    def stale_timeout_s(self) -> float:
        return self._policy.stale_timeout_s

    @property
    def engine_rpm(self) -> float | None:
        now = self._monotonic()
        with self._lock:
            return self._engine_rpm_unlocked(now)

    @property
    def engine_rpm_source(self) -> str | None:
        return "obd2" if self.engine_rpm is not None else None

    def resolve_speed(self) -> SpeedResolution:
        with self._lock:
            connection_state = self._connection_state
            speed_snapshot = self._speed_snapshot
            selected_source = self._selected_source
            snapshot = self._policy.snapshot()
        return self._policy.resolve(
            gps_enabled=selected_source is SpeedSourceKind.OBD2,
            connection_state=connection_state,
            speed_snapshot=speed_snapshot,
            snapshot=snapshot,
            live_source="obd2",
        )

    def apply_speed_source_settings(
        self,
        *,
        effective_speed_kmh: float | None,
        manual_source_selected: bool,
        stale_timeout_s: float | None = None,
        selected_source: SpeedSourceKind | str | None = None,
        obd_device_mac: str | None = None,
        obd_device_name: str | None = None,
    ) -> float | None:
        applied_speed = self._policy.apply_speed_source_settings(
            effective_speed_kmh=effective_speed_kmh,
            manual_source_selected=manual_source_selected,
            stale_timeout_s=stale_timeout_s,
        )
        with self._lock:
            if selected_source is not None:
                self._selected_source = SpeedSourceKind(selected_source)
            self._configured_device_mac = obd_device_mac
            self._configured_device_name = obd_device_name
            if (
                self._selected_source is SpeedSourceKind.OBD2
                and self._configured_device_mac is None
            ):
                self._connection_state = "disconnected"
            elif self._selected_source is not SpeedSourceKind.OBD2:
                self._connection_state = "idle"
        return applied_speed

    def scan_devices(self, *, timeout_s: int = 8) -> list[ObdDeviceSnapshot]:
        return self._admin_client.scan_devices(timeout_s=timeout_s)

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        return self._admin_client.pair_device(mac_address)

    def set_manual_source_selected(self, selected: bool) -> None:
        self._policy.set_manual_source_selected(selected)

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        return self._policy.set_speed_override_kmh(speed_kmh)

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None:
        self._policy.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)

    def status_snapshot(self, *, refresh_admin: bool = False) -> ObdStatusSnapshot:
        helper_error: str | None = None
        helper_device: ObdDeviceSnapshot | None = None
        configured_mac: str | None
        with self._lock:
            configured_mac = self._configured_device_mac
        if refresh_admin and configured_mac is not None:
            try:
                helper_device = self._admin_client.device_info(configured_mac)
            except RuntimeError as exc:
                helper_error = str(exc)
            else:
                self._apply_device_snapshot(helper_device)
        with self._lock:
            speed_mps, last_speed_ts = self._speed_snapshot
            now = self._monotonic()
            last_speed_age_s = None if last_speed_ts is None else round(now - last_speed_ts, 2)
            last_speed_kmh = None
            if isinstance(speed_mps, NUMERIC_TYPES) and not isinstance(speed_mps, bool):
                last_speed_kmh = round(float(speed_mps) * MPS_TO_KMH, 2)
            rpm_age_s = None if self._engine_rpm_ts is None else round(now - self._engine_rpm_ts, 2)
            current_error = self._last_error or helper_error
            reconnect_delay = (
                round(self._current_reconnect_delay, 1)
                if self._connection_state == "disconnected"
                else None
            )
            device_name = self._device_name
            configured_name = self._configured_device_name
            helper_name = helper_device.name if helper_device is not None else None
            effective_name = device_name or configured_name or helper_name
            obd_selected = self._selected_source is SpeedSourceKind.OBD2
            return ObdStatusSnapshot(
                configured_device_mac=self._configured_device_mac,
                configured_device_name=configured_name,
                connection_state=self._effective_connection_state_unlocked(),
                device_mac=self._device_mac or self._configured_device_mac,
                device_name=effective_name,
                paired=self._paired,
                trusted=self._trusted,
                connected=self._device_connected,
                rfcomm_channel=self._rfcomm_channel,
                last_sample_age_s=last_speed_age_s,
                last_speed_kmh=last_speed_kmh,
                last_rpm=self._engine_rpm_unlocked(now),
                rpm_sample_age_s=rpm_age_s if obd_selected else None,
                rpm_target_interval_ms=(
                    self._rpm_target_interval_ms_unlocked() if obd_selected else None
                ),
                rpm_effective_hz=self._rpm_effective_hz_unlocked() if obd_selected else None,
                request_rtt_ms=self._request_rtt_ms_unlocked() if obd_selected else None,
                timeout_count=self._timeout_count,
                error_count=self._error_count,
                poll_mode=self._poll_mode_unlocked(),
                backoff_active=obd_selected and self._rpm_interval_index > 0,
                last_error=current_error,
                last_raw_response=self._last_raw_response,
                reconnect_delay_s=reconnect_delay,
                debug_hint=self._debug_hint_unlocked(helper_error=helper_error),
            )

    async def run(self) -> None:
        session: Elm327Session | None = None
        session_device_mac: str | None = None
        reconnect_delay = _INITIAL_RECONNECT_DELAY_S
        try:
            while True:
                selected_source, configured_mac, configured_name = self._config_snapshot()
                if selected_source is not SpeedSourceKind.OBD2:
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    session, session_device_mac = await self._idle(session, session_device_mac)
                    await asyncio.sleep(_IDLE_POLL_S)
                    continue
                if configured_mac is None:
                    self._set_connection_state(
                        "disconnected",
                        error="No configured Bluetooth OBD adapter",
                    )
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    session, session_device_mac = await self._idle(session, session_device_mac)
                    await asyncio.sleep(_IDLE_POLL_S)
                    continue
                if session is not None and session_device_mac != configured_mac:
                    await asyncio.to_thread(session.close)
                    session = None
                    session_device_mac = None
                if session is None:
                    self._set_connection_state("connecting", error=None)
                    try:
                        session, device = await asyncio.to_thread(
                            self._connect_blocking,
                            configured_mac,
                            configured_name,
                        )
                    except RuntimeError as exc:
                        self._set_connection_state(
                            "disconnected",
                            error=str(exc),
                            reconnect_delay_s=reconnect_delay,
                        )
                        await asyncio.sleep(reconnect_delay)
                        reconnect_delay = min(reconnect_delay * 2.0, _MAX_RECONNECT_DELAY_S)
                        continue
                    session_device_mac = device.mac_address
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    self._apply_device_snapshot(device)
                    self._reset_poll_schedule()
                    self._set_connection_state("connected", error=None)
                wait_s = self._next_poll_wait_s()
                if wait_s > 0:
                    await asyncio.sleep(wait_s)
                    continue
                assert session is not None
                poll_result = await asyncio.to_thread(self._poll_cycle_blocking, session)
                self._apply_poll_result(poll_result)
                if poll_result.connection_lost:
                    await asyncio.to_thread(session.close)
                    session = None
                    session_device_mac = None
                    self._set_connection_state(
                        "disconnected",
                        error=self._last_error,
                        reconnect_delay_s=reconnect_delay,
                    )
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2.0, _MAX_RECONNECT_DELAY_S)
        except asyncio.CancelledError:
            if session is not None:
                await asyncio.to_thread(session.close)
            raise

    def _connect_blocking(
        self,
        mac_address: str,
        configured_name: str | None,
    ) -> tuple[Elm327Session, ObdDeviceSnapshot]:
        info = self._admin_client.device_info(mac_address)
        if not info.paired:
            raise RuntimeError("Configured OBD adapter is not paired")
        if not info.trusted:
            raise RuntimeError("Configured OBD adapter is not trusted")
        if info.rfcomm_channel is None:
            raise RuntimeError("Bluetooth OBD adapter exposes no RFCOMM serial channel")
        session = self._session_factory()
        session.connect(mac_address, info.rfcomm_channel)
        try:
            session.initialize()
        except Exception:
            session.close()
            raise
        device = replace(
            info,
            name=info.name or configured_name,
            connected=True,
        )
        return session, device

    def _poll_cycle_blocking(self, session: Elm327Session) -> _PollResult:
        now = self._monotonic()
        with self._lock:
            rpm_due = self._rpm_next_poll_at is None or now >= self._rpm_next_poll_at
            speed_due = self._speed_next_poll_at is None or now >= self._speed_next_poll_at
            rpm_timeout_s = self._rpm_request_timeout_s_unlocked()
            speed_timeout_s = self._speed_request_timeout_s_unlocked()
        rpm = (
            self._request_pid(
                session,
                command="010C",
                timeout_s=rpm_timeout_s,
                parser=parse_pid_010c_rpm,
                no_data_message="ECU returned no RPM data for PID 010C",
                parse_error_message="Unexpected RPM response for PID 010C: {response}",
            )
            if rpm_due
            else _PidPollResult.skipped()
        )
        speed = (
            self._request_pid(
                session,
                command="010D",
                timeout_s=speed_timeout_s,
                parser=parse_pid_010d_speed_kmh,
                no_data_message="ECU returned no speed data for PID 010D",
                parse_error_message="Unexpected speed response for PID 010D: {response}",
            )
            if speed_due and not (rpm.executed and rpm.error is not None)
            else _PidPollResult.skipped()
        )
        return _PollResult(rpm=rpm, speed=speed)

    def _request_pid(
        self,
        session: Elm327Session,
        *,
        command: str,
        timeout_s: float,
        parser: Callable[[str], float | None],
        no_data_message: str,
        parse_error_message: str,
    ) -> _PidPollResult:
        started_at_s = self._monotonic()
        try:
            raw_response = session.request(command, timeout_s=timeout_s)
        except ObdTransportError as exc:
            duration_s = max(0.0, self._monotonic() - started_at_s)
            transport_error = str(exc)
            timed_out = _poll_error_is_timeout(transport_error)
            if timed_out:
                transport_error = f"Timed out waiting for PID {command} response"
            else:
                transport_error = f"PID {command} request failed: {transport_error}"
            return _PidPollResult(
                value=None,
                raw_response=None,
                error=transport_error,
                duration_s=duration_s,
                timed_out=timed_out,
                no_data=False,
                executed=True,
                started_at_s=started_at_s,
                fatal_transport=not timed_out and _poll_error_is_fatal_transport(transport_error),
            )
        duration_s = max(0.0, self._monotonic() - started_at_s)
        value = parser(raw_response)
        no_data = elm_response_has_no_data(raw_response)
        error: str | None = None
        if value is None:
            if no_data:
                error = no_data_message
            else:
                error = parse_error_message.format(response=raw_response or "<empty>")
        return _PidPollResult(
            value=value,
            raw_response=raw_response,
            error=error,
            duration_s=duration_s,
            timed_out=False,
            no_data=no_data,
            executed=True,
            started_at_s=started_at_s,
        )

    def _apply_poll_result(self, result: _PollResult) -> None:
        now = self._monotonic()
        with self._lock:
            self._record_pid_metrics_unlocked(result.rpm)
            self._record_pid_metrics_unlocked(result.speed)
            self._record_rpm_cadence_unlocked(result.rpm)
            self._adapt_rpm_interval_unlocked(result.rpm)
            current_target_interval_s = self._current_rpm_target_interval_unlocked()
            if result.rpm.executed and result.rpm.started_at_s is not None:
                self._rpm_next_poll_at = result.rpm.started_at_s + current_target_interval_s
            elif self._rpm_next_poll_at is None:
                self._rpm_next_poll_at = now
            if result.speed.executed and result.speed.started_at_s is not None:
                self._speed_next_poll_at = (
                    result.speed.started_at_s + self._speed_companion_interval_unlocked()
                )
            elif self._speed_next_poll_at is None:
                self._speed_next_poll_at = now
            if (
                result.speed.value is not None
                and isinstance(result.speed.value, NUMERIC_TYPES)
                and not isinstance(result.speed.value, bool)
            ):
                speed_sample_time = self._completed_at(result.speed, fallback_now=now)
                self._speed_snapshot = (float(result.speed.value) * KMH_TO_MPS, speed_sample_time)
                self._speed_degraded = False
            elif result.speed.executed and (result.speed.error is not None or result.speed.no_data):
                self._speed_degraded = True
            if (
                result.rpm.value is not None
                and isinstance(result.rpm.value, NUMERIC_TYPES)
                and not isinstance(result.rpm.value, bool)
            ):
                rpm_sample_time = self._completed_at(result.rpm, fallback_now=now)
                self._engine_rpm = float(result.rpm.value)
                self._engine_rpm_ts = rpm_sample_time
            self._last_raw_response = result.raw_response
            self._last_error = result.rpm.error or result.speed.error
            self._device_connected = True
            self._connection_state = "connected"
            self._current_reconnect_delay = _INITIAL_RECONNECT_DELAY_S

    def _record_pid_metrics_unlocked(self, result: _PidPollResult) -> None:
        if not result.executed:
            return
        if result.duration_s is not None:
            self._avg_request_rtt_s = _update_ema(
                self._avg_request_rtt_s,
                result.duration_s,
                weight=_REQUEST_RTT_EMA_WEIGHT,
            )
        if result.error is None:
            return
        if result.timed_out:
            self._timeout_count += 1
        elif not result.no_data:
            self._error_count += 1

    def _record_rpm_cadence_unlocked(self, result: _PidPollResult) -> None:
        if not result.executed or result.started_at_s is None:
            return
        if self._last_rpm_poll_started_at is not None:
            interval_s = max(0.001, result.started_at_s - self._last_rpm_poll_started_at)
            self._effective_rpm_interval_s = _update_ema(
                self._effective_rpm_interval_s,
                interval_s,
                weight=_RPM_INTERVAL_EMA_WEIGHT,
            )
        self._last_rpm_poll_started_at = result.started_at_s

    def _adapt_rpm_interval_unlocked(self, result: _PidPollResult) -> None:
        if not result.executed:
            return
        target_interval_s = self._current_rpm_target_interval_unlocked()
        should_backoff = (
            result.error is not None
            or result.no_data
            or (result.duration_s is not None and result.duration_s > target_interval_s)
        )
        if should_backoff:
            if self._rpm_interval_index < len(self._adaptive_interval_steps) - 1:
                self._rpm_interval_index += 1
            self._rpm_stable_poll_count = 0
            return
        self._rpm_stable_poll_count += 1
        if self._rpm_interval_index <= 0 or self._rpm_stable_poll_count < _STABLE_POLLS_TO_SPEED_UP:
            return
        faster_interval_s = self._adaptive_interval_steps[self._rpm_interval_index - 1]
        reference_rtt_s = (
            self._avg_request_rtt_s if self._avg_request_rtt_s is not None else result.duration_s
        )
        if reference_rtt_s is not None and reference_rtt_s <= (faster_interval_s * 0.9):
            self._rpm_interval_index -= 1
            self._rpm_stable_poll_count = 0

    def _apply_device_snapshot(self, snapshot: ObdDeviceSnapshot) -> None:
        with self._lock:
            self._device_mac = snapshot.mac_address
            self._device_name = snapshot.name
            self._paired = snapshot.paired
            self._trusted = snapshot.trusted
            self._device_connected = snapshot.connected
            self._rfcomm_channel = snapshot.rfcomm_channel

    async def _idle(
        self,
        session: Elm327Session | None,
        session_device_mac: str | None,
    ) -> tuple[Elm327Session | None, str | None]:
        if session is not None:
            await asyncio.to_thread(session.close)
        return None, None

    def _config_snapshot(self) -> tuple[SpeedSourceKind, str | None, str | None]:
        with self._lock:
            return self._selected_source, self._configured_device_mac, self._configured_device_name

    def _set_connection_state(
        self,
        state: str,
        *,
        error: str | None,
        reconnect_delay_s: float | None = None,
    ) -> None:
        with self._lock:
            self._connection_state = state
            self._last_error = error
            self._device_connected = state == "connected"
            if reconnect_delay_s is not None:
                self._current_reconnect_delay = float(reconnect_delay_s)
            elif state == "connected":
                self._current_reconnect_delay = _INITIAL_RECONNECT_DELAY_S

    def _engine_rpm_unlocked(self, now: float) -> float | None:
        if self._selected_source is not SpeedSourceKind.OBD2:
            return None
        if (
            not isinstance(self._engine_rpm, NUMERIC_TYPES)
            or isinstance(self._engine_rpm, bool)
            or self._engine_rpm_ts is None
        ):
            return None
        if (now - self._engine_rpm_ts) > _RPM_STALE_TIMEOUT_S:
            return None
        return float(self._engine_rpm)

    def _current_rpm_target_interval_unlocked(self) -> float:
        return self._adaptive_interval_steps[self._rpm_interval_index]

    def _rpm_target_interval_ms_unlocked(self) -> int:
        return int(round(self._current_rpm_target_interval_unlocked() * 1000.0))

    def _rpm_effective_hz_unlocked(self) -> float | None:
        if self._effective_rpm_interval_s is None or self._effective_rpm_interval_s <= 0:
            return None
        return round(1.0 / self._effective_rpm_interval_s, 2)

    def _request_rtt_ms_unlocked(self) -> float | None:
        if self._avg_request_rtt_s is None:
            return None
        return round(self._avg_request_rtt_s * 1000.0, 1)

    def _speed_companion_interval_unlocked(self) -> float:
        return min(
            _MAX_SPEED_COMPANION_INTERVAL_S,
            max(
                _MIN_SPEED_COMPANION_INTERVAL_S,
                self._current_rpm_target_interval_unlocked() * _SPEED_COMPANION_INTERVAL_MULTIPLIER,
            ),
        )

    def _rpm_request_timeout_s_unlocked(self) -> float:
        return min(
            _MAX_RPM_REQUEST_TIMEOUT_S,
            max(
                _MIN_REQUEST_TIMEOUT_S,
                self._current_rpm_target_interval_unlocked() * 4.0,
            ),
        )

    def _speed_request_timeout_s_unlocked(self) -> float:
        return min(
            _MAX_SPEED_REQUEST_TIMEOUT_S,
            max(
                _MIN_REQUEST_TIMEOUT_S,
                self._current_rpm_target_interval_unlocked() * 2.0,
            ),
        )

    def _next_poll_wait_s(self) -> float:
        with self._lock:
            due_times = [
                due for due in (self._rpm_next_poll_at, self._speed_next_poll_at) if due is not None
            ]
            if not due_times:
                return 0.0
            return max(0.0, min(due_times) - self._monotonic())

    def _reset_poll_schedule(self) -> None:
        now = self._monotonic()
        with self._lock:
            self._avg_request_rtt_s = None
            self._effective_rpm_interval_s = None
            self._last_rpm_poll_started_at = None
            self._rpm_interval_index = 0
            self._rpm_next_poll_at = now
            self._rpm_stable_poll_count = 0
            self._speed_degraded = False
            self._speed_next_poll_at = now
            self._timeout_count = 0
            self._error_count = 0
            self._last_raw_response = None

    @staticmethod
    def _completed_at(result: _PidPollResult, *, fallback_now: float) -> float:
        if result.started_at_s is not None and result.duration_s is not None:
            return result.started_at_s + result.duration_s
        return fallback_now

    def _poll_mode_unlocked(self) -> str | None:
        if (
            self._selected_source is not SpeedSourceKind.OBD2
            or self._connection_state != "connected"
        ):
            return None
        base_mode = "rpm_only" if self._speed_degraded else "rpm_priority"
        return f"{base_mode}_backoff" if self._rpm_interval_index > 0 else base_mode

    def _effective_connection_state_unlocked(self) -> str:
        return self._policy.effective_connection_state(
            gps_enabled=self._selected_source is SpeedSourceKind.OBD2,
            actual_connection_state=self._connection_state,
            speed_snapshot=self._speed_snapshot,
        )

    def _debug_hint_unlocked(self, *, helper_error: str | None) -> str | None:
        if helper_error is not None:
            if "password" in helper_error.lower() or "sudo" in helper_error.lower():
                return "Install the Bluetooth OBD sudo helper and NOPASSWD sudoers entry on the Pi."
            return (
                "Bluetooth admin helper failed; try scan/pair again after "
                "power-cycling the adapter."
            )
        if self._configured_device_mac is None:
            return (
                "Pair a Bluetooth OBD adapter in Settings before selecting "
                "OBD-II as the speed source."
            )
        if not self._paired:
            return (
                "Re-run Bluetooth pairing; the configured adapter is no longer paired with the Pi."
            )
        if not self._trusted:
            return (
                "Trust the configured OBD adapter again so reconnects can succeed without prompts."
            )
        if self._rfcomm_channel is None:
            return (
                "Rescan the adapter after power-cycling it; no RFCOMM serial "
                "channel was advertised."
            )
        if self._connection_state == "disconnected":
            return (
                "Keep the adapter powered and in range; VibeSensor will keep "
                "retrying automatically."
            )
        return None
