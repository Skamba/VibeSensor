"""ESP firmware cache refresh collaborator for updater runs."""

from __future__ import annotations

from pathlib import Path

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.venv_paths import reinstall_python_executable

__all__ = ["FirmwareRefresher"]


class FirmwareRefresher:
    """Refresh the updater firmware cache independently from install orchestration."""

    __slots__ = ("_commands", "_repo", "_timeout_s", "_tracker")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        repo: Path,
        timeout_s: float,
    ) -> None:
        self._commands = commands
        self._tracker = tracker
        self._repo = repo
        self._timeout_s = timeout_s

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> None:
        self._tracker.log("Refreshing ESP firmware cache...")
        venv_python = reinstall_python_executable(self._repo)
        refresh_exe = str(Path(venv_python).with_name("vibesensor-fw-refresh"))
        refresh_args = ["--cache-dir", "/var/lib/vibesensor/firmware"]
        if pinned_tag:
            refresh_args.extend(["--tag", pinned_tag])
        refresh_cmd = (
            [
                venv_python,
                "-m",
                "vibesensor.use_cases.updates.firmware.firmware_cache",
                *refresh_args,
            ]
            if not Path(refresh_exe).is_file()
            else [refresh_exe, *refresh_args]
        )
        rc, _, stderr = await self._commands.run(
            refresh_cmd,
            phase="downloading",
            timeout=self._timeout_s,
            sudo=False,
        )
        if rc != 0:
            self._tracker.add_issue(
                "downloading",
                f"ESP firmware cache refresh failed (exit {rc})",
                stderr,
            )
            self._tracker.log("ESP firmware refresh failed; continuing with existing cache")
            return
        self._tracker.log("ESP firmware cache refresh completed successfully")
