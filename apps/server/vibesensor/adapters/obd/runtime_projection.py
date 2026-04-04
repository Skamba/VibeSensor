"""Policy-derived Bluetooth OBD status and speed projection over runtime facts."""

from __future__ import annotations

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.obd.models import ObdStatusSnapshot
from vibesensor.adapters.obd.status import build_obd_status_snapshot

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeProjection"]


class ObdRuntimeProjection:
    """Project effective OBD status and speed from raw facts plus policy."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

    @property
    def stale_timeout_s(self) -> float:
        with self._store._lock:
            return self._store.policy.stale_timeout_s

    def resolve_speed(self) -> SpeedResolution:
        with self._store._lock:
            return self._store.policy.resolve_speed(
                connection_state=self._store.state.connection_state,
                speed_snapshot=self._store.state.speed_snapshot,
            )

    def status_snapshot(self) -> ObdStatusSnapshot:
        now = self._store.monotonic()
        with self._store._lock:
            return build_obd_status_snapshot(
                self._store.state.status_facts(
                    engine_rpm=self._store.state.engine_rpm(now=now),
                    polling=self._store.polling,
                ),
                configured_device_mac=self._store.policy.configured_device_mac,
                configured_device_name=self._store.policy.configured_device_name,
                effective_connection_state=self._store.policy.effective_connection_state(
                    connection_state=self._store.state.connection_state,
                    speed_snapshot=self._store.state.speed_snapshot,
                ),
                obd_selected=self._store.policy.obd_selected,
                now_mono=now,
            )
