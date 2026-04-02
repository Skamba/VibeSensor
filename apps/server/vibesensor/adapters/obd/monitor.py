"""Bluetooth OBD live-speed runtime monitor."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from threading import RLock

from vibesensor.adapters.gps.speed_resolution import SpeedResolution, SpeedResolutionPolicy
from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.elm327 import Elm327Session
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.adapters.obd.polling import (
    ObdPidPollResult,
    ObdPollingCadence,
    ObdPollResult,
    execute_poll_plan,
)
from vibesensor.adapters.obd.status import ObdMonitorStatusState, build_obd_status_snapshot
from vibesensor.domain import SpeedSourceKind
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import KMH_TO_MPS

__all__ = ["OBDSpeedMonitor"]

_INITIAL_RECONNECT_DELAY_S = 1.0
_MAX_RECONNECT_DELAY_S = 30.0
_IDLE_POLL_S = 1.0
_DEFAULT_POLL_INTERVAL_S = 0.75
_RPM_STALE_TIMEOUT_S = 2.0


SessionFactory = Callable[[], Elm327Session]
MonotonicFn = Callable[[], float]


class OBDSpeedMonitor:
    """Manage Bluetooth RFCOMM polling plus stale/fallback resolution for OBD speed."""

    __slots__ = (
        "_admin_client",
        "_configured_device_mac",
        "_configured_device_name",
        "_connection_state",
        "_current_reconnect_delay",
        "_device_connected",
        "_device_mac",
        "_device_name",
        "_engine_rpm",
        "_engine_rpm_ts",
        "_last_error",
        "_lock",
        "_monotonic",
        "_paired",
        "_policy",
        "_polling",
        "_rfcomm_channel",
        "_selected_source",
        "_session_factory",
        "_speed_snapshot",
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
        self._polling = ObdPollingCadence(max_interval_s=poll_interval_s)
        self._policy = SpeedResolutionPolicy(
            manual_source_selected=False,
            monotonic=monotonic,
        )
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
        self._current_reconnect_delay = _INITIAL_RECONNECT_DELAY_S

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
            now = self._monotonic()
            return build_obd_status_snapshot(
                ObdMonitorStatusState(
                    effective_connection_state=self._effective_connection_state_unlocked(),
                    transport_connection_state=self._connection_state,
                    configured_device_mac=self._configured_device_mac,
                    configured_device_name=self._configured_device_name,
                    device_mac=self._device_mac,
                    device_name=self._device_name,
                    paired=self._paired,
                    trusted=self._trusted,
                    connected=self._device_connected,
                    rfcomm_channel=self._rfcomm_channel,
                    speed_snapshot=self._speed_snapshot,
                    engine_rpm=self._engine_rpm_unlocked(now),
                    engine_rpm_ts=self._engine_rpm_ts,
                    obd_selected=self._selected_source is SpeedSourceKind.OBD2,
                    last_error=self._last_error or helper_error,
                    helper_error=helper_error,
                    reconnect_delay_s=self._current_reconnect_delay,
                    polling=self._polling.snapshot(),
                ),
                now_mono=now,
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
                with self._lock:
                    wait_s = self._polling.next_wait_s(now=self._monotonic())
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
        except (OSError, RuntimeError):
            session.close()
            raise
        device = replace(
            info,
            name=info.name or configured_name,
            connected=True,
        )
        return session, device

    def _poll_cycle_blocking(self, session: Elm327Session) -> ObdPollResult:
        with self._lock:
            plan = self._polling.prepare_poll(now=self._monotonic())
        return execute_poll_plan(session, plan=plan, monotonic=self._monotonic)

    def _apply_poll_result(self, result: ObdPollResult) -> None:
        now = self._monotonic()
        with self._lock:
            self._polling.apply_result(result, now=now)
            if (
                result.speed.value is not None
                and isinstance(result.speed.value, NUMERIC_TYPES)
                and not isinstance(result.speed.value, bool)
            ):
                speed_sample_time = self._completed_at(result.speed, fallback_now=now)
                self._speed_snapshot = (float(result.speed.value) * KMH_TO_MPS, speed_sample_time)
            if (
                result.rpm.value is not None
                and isinstance(result.rpm.value, NUMERIC_TYPES)
                and not isinstance(result.rpm.value, bool)
            ):
                rpm_sample_time = self._completed_at(result.rpm, fallback_now=now)
                self._engine_rpm = float(result.rpm.value)
                self._engine_rpm_ts = rpm_sample_time
            self._last_error = result.rpm.error or result.speed.error
            self._device_connected = True
            self._connection_state = "connected"
            self._current_reconnect_delay = _INITIAL_RECONNECT_DELAY_S

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

    def _reset_poll_schedule(self) -> None:
        with self._lock:
            self._polling.reset(now=self._monotonic())

    @staticmethod
    def _completed_at(result: ObdPidPollResult, *, fallback_now: float) -> float:
        if result.started_at_s is not None and result.duration_s is not None:
            return result.started_at_s + result.duration_s
        return fallback_now

    def _effective_connection_state_unlocked(self) -> str:
        return self._policy.effective_connection_state(
            gps_enabled=self._selected_source is SpeedSourceKind.OBD2,
            actual_connection_state=self._connection_state,
            speed_snapshot=self._speed_snapshot,
        )
