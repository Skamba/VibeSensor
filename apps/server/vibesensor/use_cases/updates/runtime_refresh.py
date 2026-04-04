"""Runtime-details refresh boundary for updater workflows."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.status import (
    UpdateStatusTracker,
    collect_runtime_details,
)

__all__ = ["UpdateRuntimeDetailsRefresher"]


class UpdateRuntimeDetailsRefresher:
    """Refresh runtime/build metadata after a workflow finishes mutating the system."""

    __slots__ = ("_logger", "_repo", "_status")

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        repo: Path,
        logger: logging.Logger,
    ) -> None:
        self._status = status
        self._repo = repo
        self._logger = logger

    async def refresh(self) -> None:
        try:
            runtime_details = await asyncio.to_thread(collect_runtime_details, self._repo)
        except (OSError, UpdateError) as exc:
            self._status.fail(
                "cleanup",
                "Runtime details refresh failed",
                str(exc),
            )
            self._logger.exception("update: runtime details refresh error")
            raise UpdateCleanupError(f"Runtime details refresh failed: {exc}") from exc
        self._status.set_runtime(runtime_details)
