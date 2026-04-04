"""Post-run update cleanup separated from lifecycle state callbacks."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.status import (
    UpdateStatusController,
    UpdateStatusRecorder,
    collect_runtime_details,
)
from vibesensor.use_cases.updates.transport_coordinator import (
    PreparedUpdateTransport,
    UpdateTransportCoordinator,
)


class UpdateCleanupCoordinator:
    """Run explicit post-update cleanup steps without owning lifecycle state transitions."""

    __slots__ = (
        "_logger",
        "_repo",
        "_status_controller",
        "_status_recorder",
        "_transport_coordinator",
    )

    def __init__(
        self,
        *,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        transport_coordinator: UpdateTransportCoordinator,
        repo: Path,
        logger: logging.Logger,
    ) -> None:
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._transport_coordinator = transport_coordinator
        self._repo = repo
        self._logger = logger

    async def run(self, transport: PreparedUpdateTransport | None) -> None:
        await self._cleanup_transport_session(transport)
        await self._refresh_runtime_details()

    async def _cleanup_transport_session(
        self,
        transport: PreparedUpdateTransport | None,
    ) -> None:
        try:
            await self._transport_coordinator.cleanup_after_update(transport)
        except (OSError, UpdateError) as exc:
            self._status_recorder.add_issue("cleanup", "Transport cleanup failed", str(exc))
            self._status_controller.mark_failed()
            self._logger.exception("update: transport cleanup error")
            raise UpdateCleanupError(f"Transport cleanup failed: {exc}") from exc

    async def _refresh_runtime_details(self) -> None:
        try:
            runtime_details = await asyncio.to_thread(collect_runtime_details, self._repo)
        except (OSError, UpdateError) as exc:
            self._status_recorder.add_issue(
                "cleanup",
                "Runtime details refresh failed",
                str(exc),
            )
            self._status_controller.mark_failed()
            self._logger.exception("update: runtime details refresh error")
            raise UpdateCleanupError(f"Runtime details refresh failed: {exc}") from exc
        self._status_recorder.set_runtime(runtime_details)
