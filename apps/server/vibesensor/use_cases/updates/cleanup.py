"""Transport cleanup boundary for updater workflows."""

from __future__ import annotations

import logging

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSession

__all__ = ["UpdateTransportCleanupCoordinator"]


class UpdateTransportCleanupCoordinator:
    """Run transport-owned cleanup steps after the workflow exits."""

    __slots__ = (
        "_logger",
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
        logger: logging.Logger,
    ) -> None:
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._transport_coordinator = transport_coordinator
        self._logger = logger

    async def run(
        self,
        transport_session: UpdateTransportSession | None,
    ) -> None:
        try:
            await self._transport_coordinator.cleanup_after_update(transport_session)
        except (OSError, UpdateError) as exc:
            self._status_recorder.add_issue("cleanup", "Transport cleanup failed", str(exc))
            self._status_controller.mark_failed()
            self._logger.exception("update: transport cleanup error")
            raise UpdateCleanupError(f"Transport cleanup failed: {exc}") from exc
