from __future__ import annotations

import asyncio

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig


class _RetryableHotspotRestoreError(Exception):
    __slots__ = ("returncode",)

    def __init__(self, returncode: int) -> None:
        super().__init__(str(returncode))
        self.returncode = returncode


class _TransientUplinkCleanupError(Exception):
    """Best-effort uplink cleanup failed before hotspot restore."""


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

        failures: list[str] = []
        down_result = await self._commands.run(
            ["nmcli", "connection", "down", self._config.uplink_connection_name],
            phase="restore",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if down_result.returncode != 0:
            detail = down_result.stderr.strip() or down_result.stdout.strip() or "no output"
            failures.append(
                "connection down "
                f"{self._config.uplink_connection_name} failed "
                f"(rc={down_result.returncode}): {detail}",
            )
        delete_result = await self._commands.run(
            ["nmcli", "connection", "delete", self._config.uplink_connection_name],
            phase="restore",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if delete_result.returncode != 0:
            detail = delete_result.stderr.strip() or delete_result.stdout.strip() or "no output"
            failures.append(
                "connection delete "
                f"{self._config.uplink_connection_name} failed "
                f"(rc={delete_result.returncode}): {detail}",
            )
        if failures:
            raise _TransientUplinkCleanupError("; ".join(failures))

    async def restore_hotspot(self) -> bool:
        """Re-enable the hotspot, retrying within the configured restore budget."""

        try:
            await self.cleanup_uplink()
        except _TransientUplinkCleanupError as exc:
            self._status.log(
                "Transient uplink cleanup failed before hotspot restore; "
                f"attempting AP recovery anyway ({exc})",
            )
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.hotspot_restore_retries),
                wait=wait_fixed(self._config.hotspot_restore_delay_s),
                retry=retry_if_exception_type(_RetryableHotspotRestoreError),
                sleep=asyncio.sleep,
                reraise=True,
            ):
                with attempt:
                    result = await self._commands.run(
                        ["nmcli", "connection", "up", self._config.ap_con_name],
                        phase="restore",
                        timeout=self._config.nmcli_timeout_s,
                        sudo=True,
                    )
                    if result.returncode == 0:
                        self._status.log(
                            f"Hotspot restored on attempt {attempt.retry_state.attempt_number}",
                        )
                        return True
                    attempt_number = attempt.retry_state.attempt_number
                    self._status.log(
                        f"Hotspot restore attempt {attempt_number} failed (rc={result.returncode})",
                    )
                    raise _RetryableHotspotRestoreError(result.returncode)
        except _RetryableHotspotRestoreError:
            pass
        self._status.add_issue(
            "restoring_hotspot",
            "Failed to restore hotspot after retries",
        )
        return False
