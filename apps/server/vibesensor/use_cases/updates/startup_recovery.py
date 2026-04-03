"""Startup recovery coordination for interrupted updater runs."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import UpdateState
from vibesensor.use_cases.updates.status import (
    UpdateStatusController,
    UpdateStatusRecorder,
    UpdateStatusTracker,
)
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions

__all__ = ["UpdateStartupRecoveryCoordinator"]


class UpdateStartupRecoveryCoordinator:
    """Recover transport-owned updater state after an interrupted server restart."""

    __slots__ = ("_status_controller", "_status_recorder", "_tracker", "_transport_sessions")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        transport_sessions: UpdateTransportSessions,
    ) -> None:
        self._tracker = tracker
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._transport_sessions = transport_sessions

    async def recover(self) -> None:
        status = self._tracker.status
        if status.state != UpdateState.running or status.finished_at is not None:
            return
        self._status_recorder.add_issue("startup", "Update interrupted by server restart")
        self._status_controller.mark_interrupted()
        transport_session = self._transport_sessions.for_status(status)
        await transport_session.recover_interrupted_update()
        self._status_controller.persist()
