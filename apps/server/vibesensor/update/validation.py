"""Prerequisite validation for updater runs."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .commands import UpdateCommandExecutor
from .status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class UpdateValidationConfig:
    rollback_dir: Path
    min_free_disk_bytes: int


class UpdatePrerequisiteValidator:
    """Validates tool availability, privilege access, and disk space."""

    __slots__ = ("_commands", "_tracker", "_config")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateValidationConfig,
    ) -> None:
        self._commands = commands
        self._tracker = tracker
        self._config = config

    async def validate(self, ssid: str) -> bool:
        self._tracker.log(f"Starting update with SSID: {ssid}")
        for tool in ("nmcli", "python3"):
            if not shutil.which(tool):
                self._tracker.fail("validating", f"Required tool not found: {tool}")
                return False

        if os.geteuid() != 0:
            rc, _, _ = await self._commands.run(
                ["sudo", "-n", "true"],
                phase="validating",
                timeout=5,
                sudo=False,
            )
            if rc != 0:
                self._tracker.fail(
                    "validating",
                    "Insufficient privileges",
                    "Cannot run sudo non-interactively. In dev/Docker "
                    "environments, hotspot management is not available.",
                )
                return False

        try:
            disk_check_path = self._config.rollback_dir.parent
            if not disk_check_path.exists():
                disk_check_path = Path("/var/lib") if Path("/var/lib").exists() else Path("/")
            free_bytes = shutil.disk_usage(disk_check_path).free
            if free_bytes < self._config.min_free_disk_bytes:
                free_mb = free_bytes // (1024 * 1024)
                min_mb = self._config.min_free_disk_bytes // (1024 * 1024)
                self._tracker.fail(
                    "validating",
                    f"Insufficient disk space: {free_mb} MiB free, {min_mb} MiB required",
                )
                return False
        except OSError as exc:
            self._tracker.log(f"Could not check disk space: {exc}; proceeding anyway")

        return True