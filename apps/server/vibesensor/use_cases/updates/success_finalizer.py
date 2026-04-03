"""Success-finalization boundary for update workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.status import UpdateStatusRecorder
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSession

__all__ = ["UpdateSuccessFinalizer"]


class UpdateSuccessFinalizer:
    """Finalize successful update execution without owning install or transport prep."""

    __slots__ = ("_restart_scheduler", "_status_recorder")

    def __init__(
        self,
        *,
        status_recorder: UpdateStatusRecorder,
        restart_scheduler: UpdateRestartScheduler,
    ) -> None:
        self._status_recorder = status_recorder
        self._restart_scheduler = restart_scheduler

    async def complete(
        self,
        transport_session: UpdateTransportSession,
        *,
        message: str,
    ) -> None:
        await transport_session.complete_success(message)
        if await self._restart_scheduler.schedule():
            return
        self._status_recorder.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self._status_recorder.log("Automatic backend restart scheduling failed")
