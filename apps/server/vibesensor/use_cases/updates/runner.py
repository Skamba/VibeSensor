"""Command runner abstraction, executor, and log-redaction helpers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from dataclasses import dataclass
from typing import Protocol

from vibesensor.use_cases.updates.privilege import build_sudo_args

LOGGER = logging.getLogger(__name__)
COMMAND_KILL_WAIT_S = 5.0

__all__ = [
    "COMMAND_KILL_WAIT_S",
    "CommandExecutionReporter",
    "CommandExecutionResult",
    "CommandRunner",
    "UpdateCommandExecutor",
    "UpdateStatusCommandReporter",
    "sanitize_log_line",
]

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


@dataclass(frozen=True, slots=True)
class CommandExecutionResult:
    """One completed updater command execution."""

    returncode: int
    stdout: str
    stderr: str


class CommandExecutionReporter(Protocol):
    """Observe one updater command before and after execution."""

    def command_started(self, *, phase: str, args: list[str]) -> None: ...

    def command_finished(
        self,
        *,
        phase: str,
        result: CommandExecutionResult,
    ) -> None: ...


async def _kill_process(
    proc: asyncio.subprocess.Process,
    *,
    wait_timeout_s: float | None = None,
) -> None:
    with contextlib.suppress(ProcessLookupError, OSError):
        proc.kill()
    kill_wait_s = COMMAND_KILL_WAIT_S if wait_timeout_s is None else wait_timeout_s
    try:
        await asyncio.wait_for(proc.wait(), timeout=kill_wait_s)
    except ProcessLookupError:
        pass
    except TimeoutError:
        LOGGER.warning("Killed command process did not exit within %.1fs.", kill_wait_s)


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
            if proc is not None:
                await _kill_process(proc)
            LOGGER.warning("Command timed out after %.0fs: %s", timeout, " ".join(args))
            return (124, "", "Command timed out")
        except asyncio.CancelledError:
            # Kill the subprocess so it doesn't outlive the cancelled task.
            if proc is not None:
                await _kill_process(proc)
            raise
        except FileNotFoundError:
            LOGGER.warning("Command not found: %s", args[0] if args else "(empty)", exc_info=True)
            return (127, "", f"Command not found: {args[0]}")
        except OSError as exc:
            return (1, "", str(exc))


# ---------------------------------------------------------------------------
# Command executor
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "psk",
        "secret",
        "key",
        "wifi-sec.psk",
        "802-11-wireless-security.psk",
    },
)


class _UpdateCommandStatusSink(Protocol):
    def log(self, message: str) -> None: ...

    def redacted_args(self, args: list[str], sensitive_keys: set[str]) -> list[str]: ...


class UpdateStatusCommandReporter:
    """Render updater command telemetry through the canonical status sink."""

    __slots__ = ("_status",)

    def __init__(self, *, status: _UpdateCommandStatusSink) -> None:
        self._status = status

    def command_started(self, *, phase: str, args: list[str]) -> None:
        command = " ".join(self._status.redacted_args(args, set(_SENSITIVE_KEYS)))
        if len(command) > 500:
            command = f"{command[:497]}..."
        self._status.log(f"[{phase}] $ {command or '<empty>'}")

    def command_finished(self, *, phase: str, result: CommandExecutionResult) -> None:
        stdout_s = result.stdout.strip()
        stderr_s = result.stderr.strip()
        if stdout_s:
            self._status.log(f"[{phase}] stdout: {stdout_s[:500]}")
        if stderr_s:
            self._status.log(f"[{phase}] stderr: {stderr_s[:500]}")
        if result.returncode != 0:
            self._status.log(f"[{phase}] exit code: {result.returncode}")


class UpdateCommandExecutor:
    """Execute updater commands and optionally report telemetry through a separate reporter."""

    __slots__ = ("_reporter", "_runner")

    def __init__(
        self,
        *,
        runner: CommandRunner,
        reporter: CommandExecutionReporter | None = None,
    ) -> None:
        self._runner = runner
        self._reporter = reporter

    async def run(
        self,
        args: list[str],
        *,
        timeout: float,
        phase: str,
        sudo: bool = False,
        env: dict[str, str] | None = None,
    ) -> CommandExecutionResult:
        full_args = build_sudo_args(args) if sudo else list(args)
        if self._reporter is not None:
            self._reporter.command_started(phase=phase, args=full_args)
        rc, stdout, stderr = await self._runner.run(full_args, timeout=timeout, env=env)
        result = CommandExecutionResult(returncode=rc, stdout=stdout, stderr=stderr)
        if self._reporter is not None:
            self._reporter.command_finished(phase=phase, result=result)
        return result
