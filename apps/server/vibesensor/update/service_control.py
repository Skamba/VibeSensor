"""systemd and service-control operations for updater runs."""

from __future__ import annotations

from dataclasses import dataclass

from .commands import UpdateCommandExecutor
from .status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class UpdateServiceControlConfig:
    service_name: str
    restart_unit: str


class UpdateServiceController:
    """Owns systemd drop-in management and restart scheduling."""

    __slots__ = ("_commands", "_config", "_tracker")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateServiceControlConfig,
    ) -> None:
        self._commands = commands
        self._tracker = tracker
        self._config = config

    async def schedule_restart(self) -> bool:
        restart_attempts = [
            [
                "systemd-run",
                "--unit",
                self._config.restart_unit,
                "--on-active=2s",
                "systemctl",
                "restart",
                self._config.service_name,
            ],
            ["systemctl", "restart", self._config.service_name],
        ]
        for command in restart_attempts:
            rc, _, _ = await self._commands.run(
                command,
                phase="done",
                timeout=30,
                sudo=True,
            )
            if rc == 0:
                self._tracker.log("Scheduled backend service restart")
                return True
        return False
