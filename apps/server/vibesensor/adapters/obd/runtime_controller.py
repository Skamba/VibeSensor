"""Runtime-state coordination for Bluetooth OBD monitoring."""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import RLock

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.obd.admin_state import ObdAdminObservation
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.adapters.obd.polling import ObdPollingCadence, ObdPollPlan, ObdPollResult
from vibesensor.adapters.obd.runtime_control import (
    apply_runtime_control_decision,
    resolve_runtime_control_decision,
)
from vibesensor.adapters.obd.runtime_policy import ObdRuntimePolicy
from vibesensor.adapters.obd.runtime_state import ObdRuntimeState
from vibesensor.domain import SpeedSourceKind

__all__ = ["ObdRuntimeController"]


class ObdRuntimeController:
    """Own live runtime state, policy interpretation, and outward OBD status facts."""

    __slots__ = (
        "_lock",
        "_monotonic",
        "_polling",
        "_policy",
        "_runtime_state",
    )

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_s: float,
        initial_reconnect_delay_s: float,
        engine_rpm_stale_timeout_s: float,
    ) -> None:
        self._monotonic = monotonic
        self._polling = ObdPollingCadence(max_interval_s=poll_interval_s)
        self._lock = RLock()
        self._policy = ObdRuntimePolicy(monotonic=self._monotonic)
        self._runtime_state = ObdRuntimeState(
            initial_reconnect_delay_s=initial_reconnect_delay_s,
            engine_rpm_stale_timeout_s=engine_rpm_stale_timeout_s,
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
    def speed_snapshot(self) -> tuple[float | None, float | None]:
        with self._lock:
            return self._runtime_state.speed_snapshot

    @speed_snapshot.setter
    def speed_snapshot(self, value: tuple[float | None, float | None]) -> None:
        with self._lock:
            self._runtime_state.speed_snapshot = value

    def resolve_speed(self) -> SpeedResolution:
        with self._lock:
            return self._policy.resolve_speed(
                connection_state=self._runtime_state.connection_state,
                speed_snapshot=self._runtime_state.speed_snapshot,
            )

    def configured_device_snapshot(self) -> tuple[SpeedSourceKind, str | None, str | None]:
        with self._lock:
            return self._policy.config_snapshot()

    def configured_device_mac_snapshot(self) -> str | None:
        with self._lock:
            return self._policy.configured_device_mac

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
            apply_runtime_control_decision(
                self._runtime_state,
                resolve_runtime_control_decision(update),
            )
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
            self._runtime_state.apply_poll_result(result, now=now, polling=self._polling)
            if not result.connection_lost:
                return False
            self._runtime_state.set_connection_state(
                "disconnected",
                error=self._runtime_state.last_error,
                reconnect_delay_s=reconnect_delay_s,
            )
            return True

    def apply_admin_observation(
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

    def mark_connecting(self) -> None:
        with self._lock:
            self._runtime_state.set_connection_state(
                "connecting",
                error=None,
            )

    def mark_connected(self, snapshot: ObdDeviceSnapshot | None = None) -> None:
        with self._lock:
            if snapshot is not None:
                self._runtime_state.apply_device_snapshot(snapshot)
            self._polling.reset(now=self._monotonic())
            self._runtime_state.set_connection_state("connected", error=None)

    def mark_disconnected(
        self,
        *,
        error: str | None,
        reconnect_delay_s: float | None = None,
    ) -> None:
        with self._lock:
            self._runtime_state.set_connection_state(
                "disconnected",
                error=error,
                reconnect_delay_s=reconnect_delay_s,
            )
