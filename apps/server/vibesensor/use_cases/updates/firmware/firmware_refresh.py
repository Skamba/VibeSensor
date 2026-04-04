"""ESP firmware cache refresh collaborator for updater runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.venv_paths import reinstall_python_executable

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

    __slots__ = ("_commands", "_repo", "_status", "_timeout_s")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        repo: Path,
        timeout_s: float,
    ) -> None:
        self._commands = commands
        self._status = status
        self._repo = repo
        self._timeout_s = timeout_s

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> FirmwareRefreshResult:
        """Refresh the firmware cache and return the explicit outcome."""

        self._status.log("Refreshing ESP firmware cache...")
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
