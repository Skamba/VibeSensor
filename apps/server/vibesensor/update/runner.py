"""Command runner abstraction, executor, and log-redaction helpers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .status import UpdateStatusTracker

LOGGER = logging.getLogger(__name__)

__all__ = ["CommandRunner", "UpdateCommandExecutor", "sanitize_log_line"]

# ---------------------------------------------------------------------------
# sudo wrapper helpers
# ---------------------------------------------------------------------------

_WRAPPER_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "vibesensor_update_sudo.sh"
)


def _sudo_prefix() -> list[str]:
    """Return the sudo prefix for privileged commands."""
    if os.geteuid() == 0:
        return []
    wrapper = _WRAPPER_SCRIPT
    if wrapper.is_file():
        return ["sudo", str(wrapper)]
    return ["sudo"]


# ---------------------------------------------------------------------------
# Log sanitisation
# ---------------------------------------------------------------------------


_CREDENTIAL_RE = re.compile(r"(?i)(psk|password|secret|key)\s*[=:]\s*\S+")


def sanitize_log_line(line: str) -> str:
    """Remove potential credential leaks from log lines."""
    line = _CREDENTIAL_RE.sub(r"\1=***", line)
    return line[:500]


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------


class CommandRunner:
    """Execute shell commands.  Override for testing."""

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Return (returncode, stdout, stderr)."""
        merged_env = {**os.environ, **env} if env else None
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode if proc.returncode is not None else 0,
                stdout_bytes.decode(errors="replace"),
                stderr_bytes.decode(errors="replace"),
            )
        except TimeoutError:
            try:
                if proc is not None:
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass  # process already exited
            LOGGER.warning("Command timed out after %.0fs: %s", timeout, " ".join(args))
            return (124, "", "Command timed out")
        except asyncio.CancelledError:
            # Kill the subprocess so it doesn't outlive the cancelled task.
            if proc is not None:
                with contextlib.suppress(ProcessLookupError, OSError):
                    proc.kill()
            raise
        except FileNotFoundError:
            LOGGER.warning("Command not found: %s", args[0] if args else "(empty)", exc_info=True)
            return (127, "", f"Command not found: {args[0]}")
        except OSError as exc:
            return (1, "", str(exc))


# ---------------------------------------------------------------------------
# Command executor (wraps runner with logging + sudo)
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "psk",
        "secret",
        "key",
        "802-11-wireless-security.psk",
    },
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
