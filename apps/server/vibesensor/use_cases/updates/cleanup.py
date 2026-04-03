"""Post-run update cleanup separated from lifecycle state callbacks."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.status import UpdateStatusTracker, collect_runtime_details
from vibesensor.use_cases.updates.transport_lifecycle import UpdateTransportLifecycle


class UpdateCleanupCoordinator:
    """Run explicit post-update cleanup steps without owning lifecycle state transitions."""

    __slots__ = ("_logger", "_repo", "_tracker", "_transport_lifecycle")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        repo: Path,
        transport_lifecycle: UpdateTransportLifecycle,
        logger: logging.Logger,
    ) -> None:
        self._tracker = tracker
        self._repo = repo
        self._transport_lifecycle = transport_lifecycle
        self._logger = logger

    async def run(self) -> None:
        await self._cleanup_transport_session()
        await self._refresh_runtime_details()

    async def _cleanup_transport_session(self) -> None:
        try:
            await self._transport_lifecycle.cleanup_after_update()
        except (OSError, UpdateError) as exc:
            self._tracker.fail("cleanup", "Transport cleanup failed", str(exc))
            self._logger.exception("update: transport cleanup error")
            raise UpdateCleanupError(f"Transport cleanup failed: {exc}") from exc

    async def _refresh_runtime_details(self) -> None:
        try:
            runtime_details = await asyncio.to_thread(collect_runtime_details, self._repo)
        except (OSError, UpdateError) as exc:
            self._tracker.fail("cleanup", "Runtime details refresh failed", str(exc))
            self._logger.exception("update: runtime details refresh error")
            raise UpdateCleanupError(f"Runtime details refresh failed: {exc}") from exc
        self._tracker.set_runtime(runtime_details)
