"""Admin-side observation and control for Bluetooth OBD monitoring."""

from __future__ import annotations

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.admin_state import observe_configured_obd_device
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.runtime_controller import ObdRuntimeController

__all__ = ["ObdAdminRuntime"]


class ObdAdminRuntime:
    """Own privileged OBD admin actions separately from live connection control."""

    __slots__ = ("_admin_client", "_runtime")

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient,
        runtime: ObdRuntimeController,
    ) -> None:
        self._admin_client = admin_client
        self._runtime = runtime

    def scan_devices(self, *, timeout_s: int = 8) -> list[ObdDeviceSnapshot]:
        return self._admin_client.scan_devices(timeout_s=timeout_s)

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        return self._admin_client.pair_device(mac_address)

    def refresh_configured_device(self) -> None:
        configured_mac = self._runtime.configured_device_mac_snapshot()
        observation = observe_configured_obd_device(
            admin_client=self._admin_client,
            configured_mac=configured_mac,
        )
        self._runtime.apply_admin_observation(configured_mac, observation)
