from __future__ import annotations

import asyncio
import logging

from vibesensor.use_cases.updates.models import UpdateIssue, UpdatePhase, UpdateState
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi import UpdateWifiController
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.wifi.wifi_diagnostics import parse_wifi_diagnostics

LOGGER = logging.getLogger(__name__)
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


class UpdateWifiOrchestrator:
    """Focused Wi-Fi transition helper for updater startup and cleanup paths."""

    __slots__ = ("_controller", "_tracker")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._tracker = tracker
        self._controller = UpdateWifiController(
            commands=commands,
            tracker=tracker,
            config=config,
        )

    async def stop_hotspot(self) -> bool:
        """Stop the hotspot before the updater attempts to join an uplink."""

        return await self._controller.stop_hotspot()

    async def connect_uplink(self, ssid: str, password: str) -> bool:
        """Create and connect the transient uplink profile for this update run."""

        return await self._controller.connect_uplink(ssid, password)

    async def restore_hotspot(self) -> bool:
        """Restore the hotspot after update work completes or is interrupted."""

        return await self._controller.restore_hotspot()

    async def recover_interrupted_update(self) -> None:
        """Recover updater Wi-Fi state after a previously interrupted job."""

        self._tracker.log("startup_recover: cleaning up uplink connection")
        try:
            await self._controller.cleanup_uplink()
        except Exception as exc:
            self._tracker.add_issue(
                "startup",
                "Failed to clean up uplink connection",
                str(exc),
            )

        self._tracker.log("startup_recover: restoring hotspot")
        try:
            restored = await self.restore_hotspot()
            if restored:
                self._tracker.log("startup_recover: hotspot restored successfully")
            else:
                self._tracker.add_issue(
                    "startup",
                    "Failed to restore hotspot after interrupted update",
                )
                self._tracker.log("startup_recover: hotspot restore failed")
        except Exception as exc:
            self._tracker.add_issue(
                "startup",
                "Hotspot restore error during recovery",
                str(exc),
            )

    async def cleanup_restore_hotspot(self) -> None:
        """Restore the hotspot during cleanup without letting cancellation interrupt it."""

        try:
            restored = await asyncio.shield(self.restore_hotspot())
            if not restored:
                self._tracker.add_issue("cleanup", "Failed to restore hotspot during cleanup")
                self._tracker.log("Cleanup hotspot restore failed")
        except Exception as exc:
            self._tracker.add_issue(
                "cleanup",
                "Hotspot restore error during cleanup",
                str(exc),
            )
            LOGGER.warning("Cleanup hotspot restore failed", exc_info=True)

    async def collect_cleanup_diagnostics(self) -> list[UpdateIssue]:
        """Collect any hotspot diagnostics that should be attached to cleanup failures."""

        return await asyncio.to_thread(parse_wifi_diagnostics)

    async def complete_update_success(self, message: str) -> bool:
        """Restore the hotspot and then finalize the job as successful."""

        self._tracker.transition(UpdatePhase.restoring_hotspot)
        self._tracker.log("Restoring hotspot...")
        restored = await self.restore_hotspot()
        if not restored:
            self._tracker.status.state = UpdateState.failed
            self._tracker.persist()
            return False
        self._tracker.mark_success(message)
        return True

    async def maybe_restore_hotspot_during_cleanup(self) -> None:
        """Restore the hotspot if cleanup begins while the updater still owns Wi-Fi state."""

        status = self._tracker.status
        if status.state == UpdateState.running or status.phase in _HOTSPOT_RESTORE_PHASES:
            self._tracker.transition(UpdatePhase.restoring_hotspot)
            self._tracker.log("Restoring hotspot...")
            await self.cleanup_restore_hotspot()
