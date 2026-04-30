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
COMMAND_OUTPUT_CAPTURE_LIMIT_BYTES = 64 * 1024

__all__ = [
    "COMMAND_KILL_WAIT_S",
    "COMMAND_OUTPUT_CAPTURE_LIMIT_BYTES",
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


def _append_bounded(buffer: bytearray, chunk: bytes, *, limit_bytes: int) -> bool:
    if limit_bytes <= 0:
        buffer.clear()
        return bool(chunk)
    if len(chunk) >= limit_bytes:
        buffer[:] = chunk[-limit_bytes:]
        return True
    buffer.extend(chunk)
    excess = len(buffer) - limit_bytes
    if excess > 0:
        del buffer[:excess]
        return True
    return False


async def _read_bounded_stream(
    stream: asyncio.StreamReader | None,
    *,
    limit_bytes: int,
) -> tuple[bytes, bool]:
    if stream is None:
        return (b"", False)
    buffer = bytearray()
    truncated = False
    while chunk := await stream.read(8192):
        truncated = _append_bounded(buffer, chunk, limit_bytes=limit_bytes) or truncated
    return (bytes(buffer), truncated)


def _decode_command_output(data: bytes, *, truncated: bool, limit_bytes: int) -> str:
    decoded = data.decode(errors="replace")
    if not truncated:
        return decoded
    return f"[output truncated to last {limit_bytes} bytes]\n{decoded}"


async def _cancel_output_tasks(
    *tasks: asyncio.Task[tuple[bytes, bool]] | None,
) -> None:
    pending_tasks = [task for task in tasks if task is not None and not task.done()]
    for task in pending_tasks:
        task.cancel()
    if pending_tasks:
        await asyncio.gather(*pending_tasks, return_exceptions=True)


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
        stdout_task: asyncio.Task[tuple[bytes, bool]] | None = None
        stderr_task: asyncio.Task[tuple[bytes, bool]] | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            stdout_task = asyncio.create_task(
                _read_bounded_stream(
                    proc.stdout,
                    limit_bytes=COMMAND_OUTPUT_CAPTURE_LIMIT_BYTES,
                ),
            )
            stderr_task = asyncio.create_task(
                _read_bounded_stream(
                    proc.stderr,
                    limit_bytes=COMMAND_OUTPUT_CAPTURE_LIMIT_BYTES,
                ),
            )
            await asyncio.wait_for(proc.wait(), timeout=timeout)
            stdout_bytes, stdout_truncated = await stdout_task
            stderr_bytes, stderr_truncated = await stderr_task
            return (
                proc.returncode if proc.returncode is not None else 0,
                _decode_command_output(
                    stdout_bytes,
                    truncated=stdout_truncated,
                    limit_bytes=COMMAND_OUTPUT_CAPTURE_LIMIT_BYTES,
                ),
                _decode_command_output(
                    stderr_bytes,
                    truncated=stderr_truncated,
                    limit_bytes=COMMAND_OUTPUT_CAPTURE_LIMIT_BYTES,
                ),
            )
        except TimeoutError:
            if proc is not None:
                await _kill_process(proc)
            await _cancel_output_tasks(stdout_task, stderr_task)
            LOGGER.warning("Command timed out after %.0fs: %s", timeout, " ".join(args))
            return (124, "", "Command timed out")
        except asyncio.CancelledError:
            # Kill the subprocess so it doesn't outlive the cancelled task.
            if proc is not None:
                await _kill_process(proc)
            await _cancel_output_tasks(stdout_task, stderr_task)
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
