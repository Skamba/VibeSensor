from __future__ import annotations

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.wifi.wifi_hotspot_recovery import UpdateHotspotRecovery
from vibesensor.use_cases.updates.wifi.wifi_readiness import UpdateWifiReadiness
from vibesensor.use_cases.updates.wifi.wifi_uplink_setup import UpdateUplinkProvisioner


class UpdateWifiController:
    """Thin updater coordinator over focused Wi-Fi collaborators."""

    __slots__ = ("_config", "_hotspot", "_readiness", "_tracker", "_uplink")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._tracker = tracker
        self._config = config
        self._hotspot = UpdateHotspotRecovery(commands=commands, tracker=tracker, config=config)
        self._readiness = UpdateWifiReadiness(commands=commands, tracker=tracker, config=config)
        self._uplink = UpdateUplinkProvisioner(commands=commands, tracker=tracker, config=config)

    async def stop_hotspot(self) -> bool:
        return await self._hotspot.stop_hotspot()

    async def cleanup_uplink(self) -> None:
        await self._hotspot.cleanup_uplink()

    async def restore_hotspot(self) -> bool:
        return await self._hotspot.restore_hotspot()

    async def connect_uplink(self, ssid: str, password: str) -> bool:
        self._tracker.log(f"Connecting to Wi-Fi network: {ssid}")
        if not await self._uplink.prepare_uplink_connection(ssid, password):
            return False
        if not await self._readiness.bring_uplink_up(ssid):
            return False
        fallback = self._config.uplink_fallback_dns
        self._tracker.log(f"Wi-Fi connected successfully (client DNS fallback={fallback})")
        return await self._readiness.wait_for_dns_ready()
