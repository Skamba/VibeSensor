"""Raw observed Bluetooth OBD facts over shared runtime state."""

from __future__ import annotations

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeFacts"]


class ObdRuntimeFacts:
    """Read live OBD facts without applying selected-source policy."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

    @property
    def speed_mps(self) -> float | None:
        with self._store._lock:
            return self._store.state.speed_mps

    @property
    def engine_rpm(self) -> float | None:
        now = self._store.monotonic()
        with self._store._lock:
            return self._store.state.engine_rpm(now=now)

    @property
    def engine_rpm_source(self) -> str | None:
        return "obd2" if self.engine_rpm is not None else None
