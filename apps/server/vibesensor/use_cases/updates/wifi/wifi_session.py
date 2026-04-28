from __future__ import annotations

import asyncio
from dataclasses import dataclass

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.uplink_readiness import UpdateUplinkReadiness
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.wifi.wifi_diagnostics import parse_wifi_diagnostics
from vibesensor.use_cases.updates.wifi.wifi_hotspot_recovery import UpdateHotspotRecovery
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


@dataclass(frozen=True, slots=True)
class WifiHotspotCleanupPlan:
    """Interpret updater status into one hotspot-cleanup control plan."""

    restore_hotspot: bool
    transition_to_restore_phase: bool


def _cleanup_plan(status: UpdateJobStatus) -> WifiHotspotCleanupPlan:
    if status.state == UpdateState.running:
        return WifiHotspotCleanupPlan(restore_hotspot=True, transition_to_restore_phase=True)
    return WifiHotspotCleanupPlan(
        restore_hotspot=status.phase in _HOTSPOT_RESTORE_PHASES,
        transition_to_restore_phase=False,
    )


class UpdateWifiSession:
    """Wi-Fi transport session for updater startup, success, and cleanup."""

    __slots__ = (
        "_config",
        "_dns_readiness",
        "_hotspot",
        "_status",
        "_uplink",
    )
    transport = UpdateTransport.wifi

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._status = status
        self._config = config
        self._hotspot = UpdateHotspotRecovery(
            commands=commands,
            status=status,
            config=config,
        )
        self._dns_readiness = UpdateUplinkReadiness(
            commands=commands,
            status=status,
            config=config,
        )
        self._uplink = UpdateUplinkProvisioner(
            commands=commands,
            status=status,
            config=config,
        )

    async def _stop_hotspot(self) -> bool:
        """Stop the hotspot before the updater attempts to join an uplink."""

        return await self._hotspot.stop_hotspot()

    async def _connect_uplink(self, ssid: str, password: str) -> None:
        """Create and connect the transient uplink profile for this update run."""

        self._status.log(f"Connecting to Wi-Fi network: {ssid}")
        await self._uplink.prepare_uplink_connection(ssid, password)
        await self._uplink.bring_uplink_up(ssid)
        fallback = self._config.uplink_fallback_dns
        self._status.log(
            f"Wi-Fi connected successfully (client DNS fallback={fallback})",
        )
        await self._dns_readiness.wait_for_dns_ready()

    async def prepare(self, request: UpdateRequest) -> UpdateWifiSession:
        """Prepare the updater's Wi-Fi transport before release work begins."""

        self._status.transition(UpdatePhase.stopping_hotspot)
        if not await self._stop_hotspot():
            raise UpdateTransportError(
                "Failed to stop the hotspot before Wi-Fi update setup",
                phase=UpdatePhase.stopping_hotspot.value,
            )
        self._status.transition(UpdatePhase.connecting_wifi)
        assert request.ssid is not None  # noqa: S101
        await self._connect_uplink(request.ssid, request.password)
        return self

    async def abort_preparation(self) -> None:
        """Rollback partial Wi-Fi setup after transport preparation fails."""

        await self._cleanup_and_restore_hotspot(
            prefix="prepare_abort",
            failure_message="Failed to restore hotspot after transport preparation failure",
        )

    async def _restore_hotspot(self) -> bool:
        """Restore the hotspot after update work completes or is interrupted."""

        return await self._hotspot.restore_hotspot()

    async def recover_interrupted_update(self, _status: UpdateJobStatus) -> None:
        """Recover updater Wi-Fi state after a previously interrupted job."""

        await self._cleanup_and_restore_hotspot(
            prefix="startup_recover",
            failure_message="Failed to restore hotspot after interrupted update",
        )

    async def complete_success(self) -> None:
        """Restore the hotspot and then finalize the Wi-Fi update as successful."""

        self._status.transition(UpdatePhase.restoring_hotspot)
        self._status.log("Restoring hotspot...")
        restored = await self._restore_hotspot()
        if not restored:
            raise UpdateTransportError(
                "Failed to restore hotspot after update",
                phase=UpdatePhase.restoring_hotspot.value,
            )

    async def cleanup_after_update(self) -> None:
        """Restore hotspot ownership and attach cleanup diagnostics after a run."""

        status = self._status.status
        plan = _cleanup_plan(status)
        if plan.restore_hotspot:
            if plan.transition_to_restore_phase:
                self._status.transition(UpdatePhase.restoring_hotspot)
            self._status.log("Restoring hotspot...")
            restored = await asyncio.shield(self._restore_hotspot())
            if not restored:
                self._status.add_issue(
                    "cleanup",
                    "Failed to restore hotspot during cleanup",
                )
                self._status.log("Cleanup hotspot restore failed")
        self._status.extend_issues(await asyncio.to_thread(parse_wifi_diagnostics))

    async def _cleanup_and_restore_hotspot(
        self,
        *,
        prefix: str,
        failure_message: str,
    ) -> None:
        self._status.log(f"{prefix}: restoring hotspot")
        restored = await self._restore_hotspot()
        if restored:
            self._status.log(f"{prefix}: hotspot restored successfully")
            return
        self._status.add_issue("cleanup", failure_message)
        self._status.log(f"{prefix}: hotspot restore failed")
