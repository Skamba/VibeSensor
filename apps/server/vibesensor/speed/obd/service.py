"""The Bluetooth OBD speed/RPM service.

``ObdService`` owns the one lock around the OBD runtime state, speed-source
policy, and PID polling cadence, and exposes every operation callers need:

- live facts and speed/status projection for the speed-source services,
- speed-source settings sync from persisted settings,
- configured-device admin refresh plus scan/pair for the settings API,
- the connection-loop callbacks used by ``ObdConnectionExecutor``, and
- ``run()``, the background connection loop started by the app lifecycle.

The real work stays in focused modules: ``elm327.py`` (ELM327 transport),
``polling.py`` (PID polling), ``connection_plan.py`` / ``connection_executor.py``
(connection steps), ``runtime_state.py`` / ``runtime_policy.py`` (observed
state and speed policy), and the bluetoothctl ``admin_*`` modules.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from threading import RLock

from vibesensor.domain.speed_source import SpeedSourceKind
from vibesensor.speed.aligned_speed_context import AlignedSpeedContextSnapshot
from vibesensor.speed.obd.admin_client import ObdAdminClient
from vibesensor.speed.obd.admin_state import observe_configured_obd_device
from vibesensor.speed.obd.connection_executor import (
    ObdConnectionExecutor,
    ObdConnectionLoopState,
)
from vibesensor.speed.obd.connection_plan import (
    ObdConnectionLoopSnapshot,
    ObdConnectionStep,
    plan_connection_step,
)
from vibesensor.speed.obd.elm327 import Elm327Session
from vibesensor.speed.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.speed.obd.polling import ObdPollingCadence, ObdPollPlan, ObdPollResult
from vibesensor.speed.obd.runtime_policy import ObdRuntimePolicy
from vibesensor.speed.obd.runtime_state import ObdRuntimeState
from vibesensor.speed.speed_resolution import SpeedResolution
from vibesensor.speed.timed_observation import (
    DEFAULT_ALIGNMENT_TOLERANCE_S,
    TimedObservationLookup,
    TimedScalarObservation,
    resolve_timed_observation,
)

__all__ = ["ObdService"]

_DEFAULT_POLL_INTERVAL_S = 0.75
_RPM_STALE_TIMEOUT_S = 2.0
_INITIAL_RECONNECT_DELAY_S = 1.0
_IDLE_POLL_S = 1.0

SessionFactory = Callable[[], Elm327Session]
MonotonicFn = Callable[[], float]
SleepFn = Callable[[float], Awaitable[object]]


class ObdService:
    """Own Bluetooth OBD state, policy, polling cadence, admin refresh, and the connection loop."""

    __slots__ = (
        "_admin_client",
        "_executor",
        "_lock",
        "_monotonic",
        "_policy",
        "_polling",
        "_state",
    )

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient | None = None,
        session_factory: SessionFactory | None = None,
        monotonic: MonotonicFn = time.monotonic,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._admin_client = ObdAdminClient() if admin_client is None else admin_client
        self._lock = RLock()
        self._monotonic = monotonic
        self._polling = ObdPollingCadence(max_interval_s=poll_interval_s)
        self._policy = ObdRuntimePolicy(monotonic=monotonic)
        self._state = ObdRuntimeState(
            initial_reconnect_delay_s=_INITIAL_RECONNECT_DELAY_S,
            engine_rpm_stale_timeout_s=_RPM_STALE_TIMEOUT_S,
        )
        self._executor = ObdConnectionExecutor(
            admin_client=self._admin_client,
            obd=self,
            session_factory=Elm327Session if session_factory is None else session_factory,
            monotonic=monotonic,
            sleep=sleep,
        )

    # -- live facts ------------------------------------------------------------

    @property
    def speed_mps(self) -> float | None:
        with self._lock:
            return self._state.speed_mps

    @property
    def engine_rpm(self) -> float | None:
        now = self._monotonic()
        with self._lock:
            return self._state.engine_rpm(now=now)

    @property
    def engine_rpm_source(self) -> str | None:
        return "obd2" if self.engine_rpm is not None else None

    def engine_rpm_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> TimedObservationLookup:
        with self._lock:
            history = self._state.engine_rpm_history
            now = self._monotonic()
            rpm = self._state.engine_rpm(now=now)
            rpm_ts = self._state.engine_rpm_ts
            if not history and rpm is not None:
                if rpm is not None and rpm_ts is not None:
                    history = (
                        TimedScalarObservation(
                            value=float(rpm),
                            monotonic_s=float(rpm_ts),
                        ),
                    )
        if target_mono_s is None:
            return TimedObservationLookup(value=None, monotonic_s=None, aligned=False)
        return resolve_timed_observation(
            history,
            target_mono_s=target_mono_s,
            tolerance_s=(
                DEFAULT_ALIGNMENT_TOLERANCE_S if tolerance_s is None else float(tolerance_s)
            ),
        )

    # -- speed and status projection -------------------------------------------

    @property
    def stale_timeout_s(self) -> float:
        with self._lock:
            return self._policy.stale_timeout_s

    def resolve_speed(self) -> SpeedResolution:
        with self._lock:
            return self._policy.resolve_speed(
                connection_state=self._state.connection_state,
                speed_snapshot=self._state.speed_snapshot,
            )

    def resolve_speed_context_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> AlignedSpeedContextSnapshot:
        with self._lock:
            history = self._state.speed_history
            if not history and self._state.speed_snapshot[0] is not None:
                speed_value, speed_time = self._state.speed_snapshot
                if speed_value is not None and speed_time is not None:
                    history = (
                        TimedScalarObservation(
                            value=float(speed_value),
                            monotonic_s=float(speed_time),
                        ),
                    )
            if target_mono_s is None:
                lookup = TimedObservationLookup(value=None, monotonic_s=None, aligned=False)
            else:
                lookup = resolve_timed_observation(
                    history,
                    target_mono_s=target_mono_s,
                    tolerance_s=(
                        DEFAULT_ALIGNMENT_TOLERANCE_S if tolerance_s is None else float(tolerance_s)
                    ),
                )
            resolution = self._policy.resolve_speed(
                connection_state=self._state.connection_state,
                speed_snapshot=(lookup.value, lookup.monotonic_s),
                reference_time_s=target_mono_s,
            )
        resolved_aligned = (
            resolution.source == "obd2" and lookup.aligned and resolution.speed_mps is not None
        ) or (
            resolution.source in {"manual", "fallback_manual"} and resolution.speed_mps is not None
        )
        return AlignedSpeedContextSnapshot(
            selected_speed_source="obd2",
            resolved_speed_mps=resolution.speed_mps,
            resolved_speed_source=resolution.source,
            resolved_speed_aligned=resolved_aligned,
            gps_speed_mps=None,
            gps_speed_aligned=False,
            measured_engine_rpm=None,
            measured_engine_rpm_source=None,
            measured_engine_rpm_aligned=False,
        )

    def status_snapshot(self) -> ObdStatusSnapshot:
        now = self._monotonic()
        with self._lock:
            return self._state.status_snapshot(
                polling=self._polling.snapshot(),
                configured_device_mac=self._policy.configured_device_mac,
                configured_device_name=self._policy.configured_device_name,
                effective_connection_state=self._policy.effective_connection_state(
                    connection_state=self._state.connection_state,
                    speed_snapshot=self._state.speed_snapshot,
                ),
                obd_selected=self._policy.obd_selected,
                now_mono=now,
            )

    # -- speed-source settings sync --------------------------------------------

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
            # Deselecting OBD idles the runtime; a missing or changed adapter forces a
            # reconnect. Both forget the previously observed device and runtime error.
            reset_state: str | None = None
            if not update.obd_selected:
                reset_state = "idle"
            elif update.configured_device_missing or update.configured_device_changed:
                reset_state = "disconnected"
            if reset_state is not None:
                self._state.reset_observed_device_state(clear_runtime_error=True)
                self._state.set_connection_state(reset_state, error=None)
            return update.applied_speed_kmh

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

    # -- Bluetooth admin ---------------------------------------------------------

    def scan_obd_devices(self, *, timeout_s: int = 8) -> list[ObdDeviceSnapshot]:
        return self._admin_client.scan_devices(timeout_s=timeout_s)

    def pair_obd_device(self, mac_address: str) -> ObdDeviceSnapshot:
        return self._admin_client.pair_device(mac_address)

    def refresh_obd_status(self) -> None:
        """Refresh configured-device admin state (paired/trusted/RFCOMM) explicitly."""

        with self._lock:
            configured_mac = self._policy.configured_device_mac
        observation = observe_configured_obd_device(
            admin_client=self._admin_client,
            configured_mac=configured_mac,
        )
        with self._lock:
            self._state.apply_admin_observation(
                observed_configured_mac=configured_mac,
                current_configured_mac=self._policy.configured_device_mac,
                observation=observation,
            )

    # -- connection loop -----------------------------------------------------------

    async def run(self) -> None:
        state = ObdConnectionLoopState()
        try:
            while True:
                step = self._plan_loop_step(
                    session=state.session,
                    session_device_mac=state.session_device_mac,
                )
                state = await self._executor.execute(
                    state=state,
                    step=step,
                )
        except asyncio.CancelledError:
            await self._executor.close(state=state)
            raise

    def _plan_loop_step(
        self,
        *,
        session: Elm327Session | None,
        session_device_mac: str | None,
    ) -> ObdConnectionStep:
        with self._lock:
            selected_source, configured_mac, configured_name = self._policy.config_snapshot()
        return plan_connection_step(
            ObdConnectionLoopSnapshot(
                selected_source=selected_source,
                configured_mac=configured_mac,
                configured_name=configured_name,
                has_session=session is not None,
                session_device_mac=session_device_mac,
                poll_wait_s=self.next_wait_s() if session is not None else None,
            ),
            idle_poll_s=_IDLE_POLL_S,
        )

    def next_wait_s(self) -> float:
        with self._lock:
            return self._polling.next_wait_s(now=self._monotonic())

    def prepare_poll(self) -> ObdPollPlan:
        with self._lock:
            return self._polling.prepare_poll(now=self._monotonic())

    def apply_poll_cycle(
        self,
        result: ObdPollResult,
        *,
        reconnect_delay_s: float | None = None,
    ) -> bool:
        now = self._monotonic()
        with self._lock:
            self._state.apply_poll_result(
                result,
                now=now,
                polling=self._polling,
            )
            if not result.connection_lost:
                return False
            self._state.set_connection_state(
                "disconnected",
                error=self._state.last_error,
                reconnect_delay_s=reconnect_delay_s,
            )
            return True

    def mark_connecting(self) -> None:
        with self._lock:
            self._state.set_connection_state("connecting", error=None)

    def mark_connected(self, snapshot: ObdDeviceSnapshot | None = None) -> None:
        with self._lock:
            if snapshot is not None:
                self._state.apply_device_snapshot(snapshot)
            self._polling.reset(now=self._monotonic())
            self._state.set_connection_state("connected", error=None)

    def mark_disconnected(
        self,
        *,
        error: str | None,
        reconnect_delay_s: float | None = None,
    ) -> None:
        with self._lock:
            self._state.set_connection_state(
                "disconnected",
                error=error,
                reconnect_delay_s=reconnect_delay_s,
            )
