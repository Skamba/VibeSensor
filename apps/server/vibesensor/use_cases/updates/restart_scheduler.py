"""Schedule backend restart after a successful software update."""

from __future__ import annotations

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusRecorder


class UpdateRestartScheduler:
    """Own restart scheduling side effects for successful update runs."""

    __slots__ = ("_commands", "_restart_unit", "_service_name", "_status_recorder")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status_recorder: UpdateStatusRecorder,
        service_name: str,
        restart_unit: str,
    ) -> None:
        self._commands = commands
        self._status_recorder = status_recorder
        self._service_name = service_name
        self._restart_unit = restart_unit

    async def schedule(self) -> bool:
        restart_attempts = [
            [
                "systemd-run",
                "--unit",
                self._restart_unit,
                "--on-active=2s",
                "systemctl",
                "restart",
                self._service_name,
            ],
            ["systemctl", "restart", self._service_name],
        ]
        for command in restart_attempts:
            rc, _, _ = await self._commands.run(
                command,
                phase="done",
                timeout=30,
                sudo=True,
            )
            if rc == 0:
                self._status_recorder.log("Scheduled backend service restart")
                return True
        return False
