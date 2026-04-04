"""Shared command execution for privileged Bluetooth OBD admin actions."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

__all__ = ["BluetoothAdminSession", "CommandRunner", "HelperFailure"]

CommandRunner = Callable[[list[str], int, bool], tuple[int, str, str]]


class HelperFailure(RuntimeError):
    """Raised when a privileged Bluetooth helper action fails."""


def _coerce_text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore")
    return raw


def _default_runner(argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise HelperFailure(f"Required command is unavailable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        if not allow_timeout:
            raise HelperFailure(f"Command timed out after {timeout_s}s: {' '.join(argv)}") from exc
        return 124, _coerce_text(exc.stdout).strip(), _coerce_text(exc.stderr).strip()
    return int(completed.returncode), completed.stdout.strip(), completed.stderr.strip()


class BluetoothAdminSession:
    """Run privileged Bluetooth admin commands and prepare the controller."""

    __slots__ = ("_runner",)

    def __init__(self, *, runner: CommandRunner | None = None) -> None:
        self._runner = _default_runner if runner is None else runner

    def run(self, argv: list[str], *, timeout_s: int, allow_timeout: bool = False) -> str:
        returncode, stdout, stderr = self._runner(argv, timeout_s, allow_timeout)
        if returncode not in (0, 124):
            message = stderr or stdout or f"Command failed: {' '.join(argv)}"
            raise HelperFailure(message)
        return stdout or stderr

    def bluetoothctl(
        self,
        *args: str,
        timeout_s: int,
        allow_timeout: bool = False,
        ignore_errors: bool = False,
    ) -> str:
        try:
            return self.run(
                ["bluetoothctl", *args],
                timeout_s=timeout_s,
                allow_timeout=allow_timeout,
            )
        except HelperFailure:
            if ignore_errors:
                return ""
            raise

    def prepare_controller(self) -> None:
        self.run(["rfkill", "unblock", "bluetooth"], timeout_s=5, allow_timeout=False)
        self.run(["systemctl", "start", "bluetooth"], timeout_s=10, allow_timeout=False)
        self.bluetoothctl("power", "on", timeout_s=10)
