from __future__ import annotations

import asyncio

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig


class UpdateHotspotRecovery:
    """Manage the updater's hotspot shutdown and restoration lifecycle."""

    __slots__ = ("_commands", "_config", "_status")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._commands = commands
        self._status = status
        self._config = config

    async def stop_hotspot(self) -> bool:
        """Stop the hotspot before attempting an uplink connection."""

        self._status.log("Stopping hotspot...")
        result = await self._commands.run(
            ["nmcli", "connection", "down", self._config.ap_con_name],
            phase="stopping_hotspot",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if result.returncode != 0:
            self._status.log("Hotspot down returned non-zero; may already be inactive")
        return True

    async def cleanup_uplink(self) -> None:
        """Tear down any transient updater uplink connection state."""

        await self._commands.run(
            ["nmcli", "connection", "down", self._config.uplink_connection_name],
            phase="restore",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        await self._commands.run(
            ["nmcli", "connection", "delete", self._config.uplink_connection_name],
            phase="restore",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )

    async def restore_hotspot(self) -> bool:
        """Re-enable the hotspot, retrying within the configured restore budget."""

        await self.cleanup_uplink()
        for attempt in range(1, self._config.hotspot_restore_retries + 1):
            result = await self._commands.run(
                ["nmcli", "connection", "up", self._config.ap_con_name],
                phase="restore",
                timeout=self._config.nmcli_timeout_s,
                sudo=True,
            )
            if result.returncode == 0:
                self._status.log(f"Hotspot restored on attempt {attempt}")
                return True
            self._status.log(
                f"Hotspot restore attempt {attempt} failed (rc={result.returncode})",
            )
            if attempt < self._config.hotspot_restore_retries:
                await asyncio.sleep(self._config.hotspot_restore_delay_s)
        self._status.add_issue(
            "restoring_hotspot",
            "Failed to restore hotspot after retries",
        )
        return False
