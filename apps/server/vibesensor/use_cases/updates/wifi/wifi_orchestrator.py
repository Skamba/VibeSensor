from __future__ import annotations

import asyncio
import logging

from vibesensor.use_cases.updates.models import UpdateIssue
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi import UpdateWifiController
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.wifi.wifi_diagnostics import parse_wifi_diagnostics

LOGGER = logging.getLogger(__name__)


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
        return await self._controller.stop_hotspot()

    async def connect_uplink(self, ssid: str, password: str) -> bool:
        return await self._controller.connect_uplink(ssid, password)

    async def restore_hotspot(self) -> bool:
        return await self._controller.restore_hotspot()

    async def recover_interrupted_update(self) -> None:
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
        return await asyncio.to_thread(parse_wifi_diagnostics)
