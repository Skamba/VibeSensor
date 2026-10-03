"""ESP firmware cache refresh collaborator for updater runs."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from vibesensor.updates.models import UpdatePhase
from vibesensor.updates.runner import UpdateCommandExecutor
from vibesensor.updates.status.tracker import UpdateStatusTracker

__all__ = ["FirmwareRefreshResult", "FirmwareRefresher"]


@dataclass(frozen=True, slots=True)
class FirmwareRefreshResult:
    """Explicit firmware-cache refresh outcome returned to workflow callers."""

    succeeded: bool
    phase: UpdatePhase = UpdatePhase.downloading
    message: str = ""
    detail: str = ""

    @classmethod
    def success(cls) -> FirmwareRefreshResult:
        return cls(succeeded=True)

    @classmethod
    def failure(
        cls,
        *,
        message: str,
        detail: str = "",
        phase: UpdatePhase = UpdatePhase.downloading,
    ) -> FirmwareRefreshResult:
        return cls(
            succeeded=False,
            phase=phase,
            message=message,
            detail=detail,
        )


class FirmwareRefresher:
    """Run one firmware-cache refresh command and return an explicit outcome."""

    __slots__ = ("_commands", "_status", "_timeout_s")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        timeout_s: float,
    ) -> None:
        self._commands = commands
        self._status = status
        self._timeout_s = timeout_s

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> FirmwareRefreshResult:
        """Refresh the firmware cache and return the explicit outcome."""

        self._status.log("Refreshing ESP firmware cache...")
        refresh_cmd = [
            sys.executable,
            "-m",
            "vibesensor.updates.firmware.firmware_cache",
            "--cache-dir",
            "/var/lib/vibesensor/firmware",
        ]
        if pinned_tag:
            refresh_cmd.extend(["--tag", pinned_tag])
        result = await self._commands.run(
            refresh_cmd,
            phase="downloading",
            timeout=self._timeout_s,
            sudo=False,
        )
        if result.returncode != 0:
            return FirmwareRefreshResult.failure(
                message=f"ESP firmware cache refresh failed (exit {result.returncode})",
                detail=result.stderr,
            )
        self._status.log("ESP firmware cache refresh completed successfully")
        return FirmwareRefreshResult.success()
