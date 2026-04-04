"""Configured-device OBD admin observation over runtime state."""

from __future__ import annotations

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.admin_state import observe_configured_obd_device
from vibesensor.adapters.obd.runtime_store import ObdRuntimeStore

__all__ = ["ObdAdminRuntime"]


class ObdAdminRuntime:
    """Refresh configured-device admin state without exposing raw client actions."""

    __slots__ = ("_admin_client", "_store")

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient,
        store: ObdRuntimeStore,
    ) -> None:
        self._admin_client = admin_client
        self._store = store

    def refresh_configured_device(self) -> None:
        with self._store._lock:
            configured_mac = self._store.policy.configured_device_mac
        observation = observe_configured_obd_device(
            admin_client=self._admin_client,
            configured_mac=configured_mac,
        )
        with self._store._lock:
            self._store.state.apply_admin_observation(
                observed_configured_mac=configured_mac,
                current_configured_mac=self._store.policy.configured_device_mac,
                observation=observation,
            )
