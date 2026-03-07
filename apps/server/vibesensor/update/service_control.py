"""systemd and service-control operations for updater runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .commands import UpdateCommandExecutor
from .status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class UpdateServiceControlConfig:
    service_name: str
    restart_unit: str
    contracts_dir: Path
    env_dropin: Path


class UpdateServiceController:
    """Owns systemd drop-in management and restart scheduling."""

    __slots__ = ("_commands", "_tracker", "_config")

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

    async def ensure_service_contracts_env(self) -> None:
        if not self._config.contracts_dir.is_dir():
            return
        dropin_body = (
            "[Service]\n"
            f"Environment=VIBESENSOR_CONTRACTS_DIR={self._config.contracts_dir}\n"
        )
        script = (
            "from pathlib import Path; "
            f"p=Path({str(self._config.env_dropin)!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"content={dropin_body!r}; "
            "changed=(not p.exists()) or (p.read_text(encoding='utf-8')!=content); "
            "p.write_text(content, encoding='utf-8'); "
            "print('changed' if changed else 'unchanged')"
        )
        rc, stdout, stderr = await self._commands.run(
            ["python3", "-c", script],
            phase="done",
            timeout=15,
            sudo=True,
        )
        if rc != 0:
            self._tracker.add_issue(
                "done",
                "Failed to configure contracts environment for service",
                stderr,
            )
            return
        if "changed" not in (stdout or ""):
            return
        rc, _, stderr = await self._commands.run(
            ["systemctl", "daemon-reload"],
            phase="done",
            timeout=15,
            sudo=True,
        )
        if rc != 0:
            self._tracker.add_issue(
                "done",
                "Failed to reload systemd after contracts environment update",
                stderr,
            )
            return
        self._tracker.log("Updated systemd drop-in for shared contracts directory")