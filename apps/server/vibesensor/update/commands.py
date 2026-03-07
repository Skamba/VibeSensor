"""Command execution boundary for updater side effects."""

from __future__ import annotations

from .runner import CommandRunner, _sudo_prefix
from .status import UpdateStatusTracker

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "psk",
        "secret",
        "key",
        "802-11-wireless-security.psk",
    }
)


class UpdateCommandExecutor:
    """Executes commands and reports logs through the update status tracker."""

    __slots__ = ("_runner", "_tracker")

    def __init__(self, *, runner: CommandRunner, tracker: UpdateStatusTracker) -> None:
        self._runner = runner
        self._tracker = tracker

    async def run(
        self,
        args: list[str],
        *,
        timeout: float,
        phase: str,
        sudo: bool = False,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        full_args = [*_sudo_prefix(), *args] if sudo else list(args)
        command = " ".join(self._tracker.redacted_args(full_args, set(_SENSITIVE_KEYS)))
        if len(command) > 500:
            command = f"{command[:497]}..."
        self._tracker.log(f"[{phase}] $ {command or '<empty>'}")
        rc, stdout, stderr = await self._runner.run(full_args, timeout=timeout, env=env)
        stdout_s = stdout.strip()
        stderr_s = stderr.strip()
        if stdout_s:
            self._tracker.log(f"[{phase}] stdout: {stdout_s[:500]}")
        if stderr_s:
            self._tracker.log(f"[{phase}] stderr: {stderr_s[:500]}")
        if rc != 0:
            self._tracker.log(f"[{phase}] exit code: {rc}")
        return rc, stdout, stderr