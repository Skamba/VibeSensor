"""Admin-refresh mutation surface over shared Bluetooth OBD runtime state."""

from __future__ import annotations

from vibesensor.adapters.obd.admin_state import ObdAdminObservation

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeAdminState"]


class ObdRuntimeAdminState:
    """Apply configured-device admin observations without exposing connection-loop controls."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

    def configured_device_mac_snapshot(self) -> str | None:
        with self._store._lock:
            return self._store.policy.configured_device_mac

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
