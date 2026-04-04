"""Connection-loop mutation surface over shared Bluetooth OBD state."""

from __future__ import annotations

from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.polling import ObdPollResult

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeConnectionControl"]


class ObdRuntimeConnectionControl:
    """Own connection-loop state mutation over shared policy, polling, and state."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

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
