"""Startup recovery coordination for interrupted updater runs."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import UpdateState
from vibesensor.use_cases.updates.status import (
    UpdateStatusController,
    UpdateStatusRecorder,
    UpdateStatusSession,
)
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator

__all__ = ["UpdateStartupRecoveryCoordinator"]


class UpdateStartupRecoveryCoordinator:
    """Recover transport-owned updater state after an interrupted server restart."""

    __slots__ = (
        "_status_controller",
        "_status_recorder",
        "_status_session",
        "_transport_coordinator",
    )

    def __init__(
        self,
        *,
        status_session: UpdateStatusSession,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        transport_coordinator: UpdateTransportCoordinator,
    ) -> None:
        self._status_session = status_session
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._transport_coordinator = transport_coordinator

    async def recover(self) -> None:
        status = self._status_session.status
        if status.state != UpdateState.running or status.finished_at is not None:
            return
        self._status_recorder.add_issue("startup", "Update interrupted by server restart")
        self._status_controller.mark_interrupted()
        await self._transport_coordinator.recover_interrupted(status)
        self._status_controller.persist()
