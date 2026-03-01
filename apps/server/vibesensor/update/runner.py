"""Command runner abstraction and log-redaction helpers."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

LOGGER = logging.getLogger(__name__)

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


def sanitize_log_line(line: str) -> str:
    """Remove potential credential leaks from log lines."""
    line = re.sub(r"(?i)(psk|password|secret|key)\s*[=:]\s*\S+", r"\1=***", line)
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
        merged_env = {**os.environ, **(env or {})}
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode or 0,
                stdout_bytes.decode(errors="replace"),
                stderr_bytes.decode(errors="replace"),
            )
        except TimeoutError:
            try:
                proc.kill()  # type: ignore[union-attr]
                await proc.wait()  # type: ignore[union-attr]
            except ProcessLookupError:
                pass  # process already exited
            LOGGER.warning("Command timed out after %.0fs: %s", timeout, " ".join(args))
            return (124, "", "Command timed out")
        except FileNotFoundError:
            return (127, "", f"Command not found: {args[0]}")
        except OSError as exc:
            return (1, "", str(exc))
