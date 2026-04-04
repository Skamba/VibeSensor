"""Connection/admin mutation surface over shared Bluetooth OBD runtime state."""

from __future__ import annotations

from vibesensor.adapters.obd.admin_state import ObdAdminObservation
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.polling import ObdPollPlan, ObdPollResult
from vibesensor.domain import SpeedSourceKind

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeConnectionState"]


class ObdRuntimeConnectionState:
    """Own connection-loop/admin mutation over shared policy, polling, and observed state."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

    def configured_device_snapshot(self) -> tuple[SpeedSourceKind, str | None, str | None]:
        with self._store._lock:
            return self._store.policy.config_snapshot()

    def configured_device_mac_snapshot(self) -> str | None:
        with self._store._lock:
            return self._store.policy.configured_device_mac

    def next_wait_s(self) -> float:
        with self._store._lock:
            return self._store.polling.next_wait_s(now=self._store.monotonic())

    def prepare_poll(self) -> ObdPollPlan:
        with self._store._lock:
            return self._store.polling.prepare_poll(now=self._store.monotonic())

    def apply_poll_cycle(
        self,
        result: ObdPollResult,
        *,
        reconnect_delay_s: float | None = None,
    ) -> bool:
        now = self._store.monotonic()
        with self._store._lock:
            self._store.state.apply_poll_result(
                result,
                now=now,
                polling=self._store.polling,
            )
            if not result.connection_lost:
                return False
            self._store.state.set_connection_state(
                "disconnected",
                error=self._store.state.last_error,
                reconnect_delay_s=reconnect_delay_s,
            )
            return True

    def apply_admin_observation(
        self,
        configured_mac: str | None,
        observation: ObdAdminObservation,
    ) -> None:
        with self._store._lock:
            self._store.state.apply_admin_observation(
                observed_configured_mac=configured_mac,
                current_configured_mac=self._store.policy.configured_device_mac,
                observation=observation,
            )

    def mark_connecting(self) -> None:
        with self._store._lock:
            self._store.state.set_connection_state("connecting", error=None)

    def mark_connected(self, snapshot: ObdDeviceSnapshot | None = None) -> None:
        with self._store._lock:
            if snapshot is not None:
                self._store.state.apply_device_snapshot(snapshot)
            self._store.polling.reset(now=self._store.monotonic())
            self._store.state.set_connection_state("connected", error=None)

    def mark_disconnected(
        self,
        *,
        error: str | None,
        reconnect_delay_s: float | None = None,
    ) -> None:
        with self._store._lock:
            self._store.state.set_connection_state(
                "disconnected",
                error=error,
                reconnect_delay_s=reconnect_delay_s,
            )
