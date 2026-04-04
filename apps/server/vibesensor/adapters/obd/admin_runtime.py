"""Configured-device OBD admin observation over runtime state."""

from __future__ import annotations

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.admin_state import observe_configured_obd_device
from vibesensor.adapters.obd.runtime_connection_state import ObdRuntimeConnectionState

__all__ = ["ObdAdminRuntime"]


class ObdAdminRuntime:
    """Refresh configured-device admin state without exposing raw client actions."""

    __slots__ = ("_admin_client", "_runtime")

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient,
        connection_state: ObdRuntimeConnectionState,
    ) -> None:
        self._admin_client = admin_client
        self._runtime = connection_state

    def refresh_configured_device(self) -> None:
        configured_mac = self._runtime.configured_device_mac_snapshot()
        observation = observe_configured_obd_device(
            admin_client=self._admin_client,
            configured_mac=configured_mac,
        )
        self._runtime.apply_admin_observation(configured_mac, observation)
