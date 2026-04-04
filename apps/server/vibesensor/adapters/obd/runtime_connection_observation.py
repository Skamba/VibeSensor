"""Connection-loop observation surface over shared Bluetooth OBD runtime state."""

from __future__ import annotations

from vibesensor.adapters.obd.polling import ObdPollPlan
from vibesensor.domain import SpeedSourceKind

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeConnectionObservation"]


class ObdRuntimeConnectionObservation:
    """Read connection-loop planning inputs without mutating runtime state."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

    def configured_device_snapshot(self) -> tuple[SpeedSourceKind, str | None, str | None]:
        with self._store._lock:
            return self._store.policy.config_snapshot()

    def next_wait_s(self) -> float:
        with self._store._lock:
            return self._store.polling.next_wait_s(now=self._store.monotonic())

    def prepare_poll(self) -> ObdPollPlan:
        with self._store._lock:
            return self._store.polling.prepare_poll(now=self._store.monotonic())
