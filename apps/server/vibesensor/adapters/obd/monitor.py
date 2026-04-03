"""Bluetooth OBD live-speed runtime monitor."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from threading import RLock

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.admin_state import (
    ObdAdminObservation,
    observe_configured_obd_device,
)
from vibesensor.adapters.obd.elm327 import Elm327Session
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.adapters.obd.polling import (
    ObdPollingCadence,
    ObdPollResult,
    execute_poll_plan,
)
from vibesensor.adapters.obd.runtime_policy import ObdRuntimePolicy
from vibesensor.adapters.obd.runtime_state import ObdRuntimeState
from vibesensor.domain import SpeedSourceKind
from vibesensor.shared.operational_errors import OperationalError, ServiceUnavailableError

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
        "_lock",
        "_monotonic",
        "_polling",
        "_policy",
        "_runtime_state",
        "_session_factory",
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
        self._lock = RLock()
        self._policy = ObdRuntimePolicy(monotonic=self._monotonic)
        self._runtime_state = ObdRuntimeState(
            initial_reconnect_delay_s=_INITIAL_RECONNECT_DELAY_S,
            engine_rpm_stale_timeout_s=_RPM_STALE_TIMEOUT_S,
        )

    @property
    def speed_mps(self) -> float | None:
        with self._lock:
            return self._runtime_state.speed_mps

    @property
    def stale_timeout_s(self) -> float:
        with self._lock:
            return self._policy.stale_timeout_s

    @property
    def engine_rpm(self) -> float | None:
        now = self._monotonic()
        with self._lock:
            return self._runtime_state.engine_rpm(now=now, obd_selected=self._policy.obd_selected)

    @property
    def engine_rpm_source(self) -> str | None:
        return "obd2" if self.engine_rpm is not None else None

    @property
    def _speed_snapshot(self) -> tuple[float | None, float | None]:
        with self._lock:
            return self._runtime_state.speed_snapshot

    @_speed_snapshot.setter
    def _speed_snapshot(self, value: tuple[float | None, float | None]) -> None:
        with self._lock:
            self._runtime_state.speed_snapshot = value

    def resolve_speed(self) -> SpeedResolution:
        with self._lock:
            return self._policy.resolve_speed(
                connection_state=self._runtime_state.connection_state,
                speed_snapshot=self._runtime_state.speed_snapshot,
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
        with self._lock:
            update = self._policy.apply_speed_source_settings(
                effective_speed_kmh=effective_speed_kmh,
                manual_source_selected=manual_source_selected,
                stale_timeout_s=stale_timeout_s,
                selected_source=selected_source,
                obd_device_mac=obd_device_mac,
                obd_device_name=obd_device_name,
            )
            if update.configured_device_changed:
                self._runtime_state.reset_observed_device_state(clear_runtime_error=True)
                if update.obd_selected and not update.configured_device_missing:
                    self._runtime_state.set_connection_state("disconnected", error=None)
            if update.configured_device_missing:
                self._runtime_state.set_connection_state("disconnected", error=None)
                self._runtime_state.reset_observed_device_state(clear_runtime_error=True)
            elif not update.obd_selected:
                self._runtime_state.set_connection_state("idle", error=None)
                self._runtime_state.reset_observed_device_state(clear_runtime_error=True)
            return update.applied_speed_kmh

    def scan_devices(self, *, timeout_s: int = 8) -> list[ObdDeviceSnapshot]:
        return self._admin_client.scan_devices(timeout_s=timeout_s)

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        return self._admin_client.pair_device(mac_address)

    def set_manual_source_selected(self, selected: bool) -> None:
        with self._lock:
            self._policy.set_manual_source_selected(selected)

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        with self._lock:
            return self._policy.set_speed_override_kmh(speed_kmh)

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None:
        with self._lock:
            self._policy.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)

    def refresh_admin_state(self) -> None:
        configured_mac = self._configured_device_mac_snapshot()
        observation = observe_configured_obd_device(
            admin_client=self._admin_client,
            configured_mac=configured_mac,
        )
        self._apply_admin_observation(configured_mac, observation)

    def status_snapshot(self) -> ObdStatusSnapshot:
        with self._lock:
            now = self._monotonic()
            return self._runtime_state.status_snapshot(
                configured_device_mac=self._policy.configured_device_mac,
                configured_device_name=self._policy.configured_device_name,
                effective_connection_state=self._policy.effective_connection_state(
                    connection_state=self._runtime_state.connection_state,
                    speed_snapshot=self._runtime_state.speed_snapshot,
                ),
                obd_selected=self._policy.obd_selected,
                now=now,
                polling=self._polling,
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
                    except (OperationalError, RuntimeError) as exc:
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
                        error=self._runtime_state.last_error,
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
            raise ServiceUnavailableError("Configured OBD adapter is not paired")
        if not info.trusted:
            raise ServiceUnavailableError("Configured OBD adapter is not trusted")
        if info.rfcomm_channel is None:
            raise ServiceUnavailableError("Bluetooth OBD adapter exposes no RFCOMM serial channel")
        session = self._session_factory()
        session.connect(mac_address, info.rfcomm_channel)
        try:
            session.initialize()
        except (OSError, OperationalError, RuntimeError):
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
            self._runtime_state.apply_poll_result(result, now=now, polling=self._polling)

    def _apply_device_snapshot(self, snapshot: ObdDeviceSnapshot) -> None:
        with self._lock:
            self._runtime_state.apply_device_snapshot(snapshot)

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
            return self._policy.config_snapshot()

    def _configured_device_mac_snapshot(self) -> str | None:
        with self._lock:
            return self._policy.configured_device_mac

    def _apply_admin_observation(
        self,
        configured_mac: str | None,
        observation: ObdAdminObservation,
    ) -> None:
        with self._lock:
            self._runtime_state.apply_admin_observation(
                observed_configured_mac=configured_mac,
                current_configured_mac=self._policy.configured_device_mac,
                observation=observation,
            )

    def _set_connection_state(
        self,
        state: str,
        *,
        error: str | None,
        reconnect_delay_s: float | None = None,
    ) -> None:
        with self._lock:
            self._runtime_state.set_connection_state(
                state,
                error=error,
                reconnect_delay_s=reconnect_delay_s,
            )

    def _reset_poll_schedule(self) -> None:
        with self._lock:
            self._polling.reset(now=self._monotonic())
