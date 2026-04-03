"""Success-finalization boundary for update workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSession

__all__ = ["UpdateSuccessFinalizer"]


class UpdateSuccessFinalizer:
    """Finalize successful update execution without owning install or transport prep."""

    __slots__ = ("_restart_scheduler", "_tracker")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        restart_scheduler: UpdateRestartScheduler,
    ) -> None:
        self._tracker = tracker
        self._restart_scheduler = restart_scheduler

    async def complete(self, transport_session: UpdateTransportSession, *, message: str) -> bool:
        if not await transport_session.complete_success(message):
            return False
        if await self._restart_scheduler.schedule():
            return True
        self._tracker.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self._tracker.log("Automatic backend restart scheduling failed")
        return True
