"""Runtime-details refresh boundary for updater workflows."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.shared.structured_logging import log_extra
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
            self._logger.exception(
                "update: runtime details refresh error",
                extra=log_extra(
                    event="update_runtime_refresh_error",
                    update_phase="cleanup",
                    repo_path=str(self._repo),
                ),
            )
            raise UpdateCleanupError(
                "Runtime details refresh failed",
                phase="cleanup",
                detail=str(exc),
            ) from exc
        self._status.set_runtime(runtime_details)
