"""Read-side observation and status projection for Bluetooth OBD runtime state."""

from __future__ import annotations

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.obd.models import ObdStatusSnapshot

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeObservation"]


class ObdRuntimeObservation:
    """Read-only view over live OBD speed, RPM, and status facts."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

    @property
    def speed_mps(self) -> float | None:
        with self._store._lock:
            return self._store.state.speed_mps

    @property
    def stale_timeout_s(self) -> float:
        with self._store._lock:
            return self._store.policy.stale_timeout_s

    @property
    def engine_rpm(self) -> float | None:
        now = self._store.monotonic()
        with self._store._lock:
            return self._store.state.engine_rpm(
                now=now,
                obd_selected=self._store.policy.obd_selected,
            )

    @property
    def engine_rpm_source(self) -> str | None:
        return "obd2" if self.engine_rpm is not None else None

    def resolve_speed(self) -> SpeedResolution:
        with self._store._lock:
            return self._store.policy.resolve_speed(
                connection_state=self._store.state.connection_state,
                speed_snapshot=self._store.state.speed_snapshot,
            )

    def status_snapshot(self) -> ObdStatusSnapshot:
        with self._store._lock:
            now = self._store.monotonic()
            return self._store.state.status_snapshot(
                configured_device_mac=self._store.policy.configured_device_mac,
                configured_device_name=self._store.policy.configured_device_name,
                effective_connection_state=self._store.policy.effective_connection_state(
                    connection_state=self._store.state.connection_state,
                    speed_snapshot=self._store.state.speed_snapshot,
                ),
                obd_selected=self._store.policy.obd_selected,
                now=now,
                polling=self._store.polling,
            )
