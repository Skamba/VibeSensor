from __future__ import annotations

import asyncio

from vibesensor.use_cases.updates.models import (
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.wifi.wifi_diagnostics import parse_wifi_diagnostics
from vibesensor.use_cases.updates.wifi.wifi_hotspot_recovery import UpdateHotspotRecovery
from vibesensor.use_cases.updates.wifi.wifi_readiness import UpdateWifiReadiness
from vibesensor.use_cases.updates.wifi.wifi_uplink_setup import UpdateUplinkProvisioner

_HOTSPOT_RESTORE_PHASES = frozenset(
    {
        UpdatePhase.stopping_hotspot,
        UpdatePhase.connecting_wifi,
        UpdatePhase.checking,
        UpdatePhase.downloading,
        UpdatePhase.installing,
        UpdatePhase.restoring_hotspot,
    }
)


class UpdateWifiSession:
    """Wi-Fi transport session for updater startup, success, and cleanup."""

    __slots__ = ("_config", "_hotspot", "_readiness", "_tracker", "_uplink")
    transport = UpdateTransport.wifi

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
        """Stop the hotspot before the updater attempts to join an uplink."""

        return await self._hotspot.stop_hotspot()

    async def connect_uplink(self, ssid: str, password: str) -> bool:
        """Create and connect the transient uplink profile for this update run."""

        self._tracker.log(f"Connecting to Wi-Fi network: {ssid}")
        if not await self._uplink.prepare_uplink_connection(ssid, password):
            return False
        if not await self._readiness.bring_uplink_up(ssid):
            return False
        fallback = self._config.uplink_fallback_dns
        self._tracker.log(f"Wi-Fi connected successfully (client DNS fallback={fallback})")
        return await self._readiness.wait_for_dns_ready()

    async def prepare(self, request: UpdateRequest) -> bool:
        """Prepare the updater's Wi-Fi transport before release work begins."""

        self._tracker.transition(UpdatePhase.stopping_hotspot)
        if not await self.stop_hotspot():
            return False
        self._tracker.transition(UpdatePhase.connecting_wifi)
        assert request.ssid is not None  # noqa: S101
        return await self.connect_uplink(request.ssid, request.password)

    async def restore_hotspot(self) -> bool:
        """Restore the hotspot after update work completes or is interrupted."""

        return await self._hotspot.restore_hotspot()

    async def recover_interrupted_update(self) -> None:
        """Recover updater Wi-Fi state after a previously interrupted job."""

        if self._tracker.status.transport != UpdateTransport.wifi:
            return
        self._tracker.log("startup_recover: cleaning up uplink connection")
        await self._hotspot.cleanup_uplink()

        self._tracker.log("startup_recover: restoring hotspot")
        restored = await self.restore_hotspot()
        if restored:
            self._tracker.log("startup_recover: hotspot restored successfully")
        else:
            self._tracker.add_issue(
                "startup",
                "Failed to restore hotspot after interrupted update",
            )
            self._tracker.log("startup_recover: hotspot restore failed")

    async def complete_success(self, message: str) -> bool:
        """Restore the hotspot and then finalize the Wi-Fi update as successful."""

        if self._tracker.status.transport != UpdateTransport.wifi:
            self._tracker.mark_success(message)
            return True
        self._tracker.transition(UpdatePhase.restoring_hotspot)
        self._tracker.log("Restoring hotspot...")
        restored = await self.restore_hotspot()
        if not restored:
            self._tracker.fail(
                UpdatePhase.restoring_hotspot,
                "Failed to restore hotspot after update",
            )
            return False
        self._tracker.mark_success(message)
        return True

    async def cleanup_after_update(self) -> None:
        """Restore hotspot ownership and attach cleanup diagnostics after a run."""

        if self._tracker.status.transport != UpdateTransport.wifi:
            return
        status = self._tracker.status
        if status.state == UpdateState.running or status.phase in _HOTSPOT_RESTORE_PHASES:
            if status.state == UpdateState.running:
                self._tracker.transition(UpdatePhase.restoring_hotspot)
            self._tracker.log("Restoring hotspot...")
            restored = await asyncio.shield(self.restore_hotspot())
            if not restored:
                self._tracker.add_issue("cleanup", "Failed to restore hotspot during cleanup")
                self._tracker.log("Cleanup hotspot restore failed")
        self._tracker.extend_issues(await asyncio.to_thread(parse_wifi_diagnostics))
