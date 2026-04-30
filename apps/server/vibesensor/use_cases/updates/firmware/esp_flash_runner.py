"""Subprocess runner for streaming ESP flash command output."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

from vibesensor.use_cases.updates.firmware.esp_flash_types import FlashCommandRunner

LOGGER = logging.getLogger(__name__)
FLASH_CANCELLED_RETURN_CODE = 130

__all__ = ["FLASH_CANCELLED_RETURN_CODE", "SubprocessFlashCommandRunner"]


class SubprocessFlashCommandRunner(FlashCommandRunner):
    """Execute flash commands and stream combined stdout/stderr lines."""

    async def run(
        self,
        args: list[str],
        *,
        cwd: str,
        line_cb: Callable[[str], None],
        cancel_event: asyncio.Event,
        timeout_s: float | None = None,
    ) -> int:
        """Run one flash subprocess, streaming lines until exit, cancel, or timeout."""

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if proc.stdout is None:  # pragma: no cover – PIPE always sets stdout
            raise RuntimeError("subprocess stdout is None despite PIPE setting")
        started_at = time.monotonic()
        cancelled = False
        while proc.returncode is None:
            if cancel_event.is_set():
                line_cb("Flash cancelled by request")
                cancelled = True
                proc.terminate()
                break
            if timeout_s is not None and (time.monotonic() - started_at) > timeout_s:
                line_cb(f"Command timed out after {int(timeout_s)}s")
                proc.terminate()
                await proc.wait()
                return 124
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.25)
            except TimeoutError:
                continue
            if not line:
                await proc.wait()
                break
            line_cb(line.decode("utf-8", errors="replace").rstrip("\n"))
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            LOGGER.warning("Process did not exit after SIGTERM; sending SIGKILL.")
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
        if cancelled:
            return FLASH_CANCELLED_RETURN_CODE
        return proc.returncode or 0
