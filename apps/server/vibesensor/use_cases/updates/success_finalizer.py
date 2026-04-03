"""Success-finalization boundary for update workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_lifecycle import UpdateTransportLifecycle

__all__ = ["UpdateSuccessFinalizer"]


class UpdateSuccessFinalizer:
    """Finalize successful update execution without owning install or transport prep."""

    __slots__ = ("_restart_scheduler", "_tracker", "_transport_lifecycle")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        restart_scheduler: UpdateRestartScheduler,
        transport_lifecycle: UpdateTransportLifecycle,
    ) -> None:
        self._tracker = tracker
        self._restart_scheduler = restart_scheduler
        self._transport_lifecycle = transport_lifecycle

    async def complete(self, *, message: str) -> None:
        await self._transport_lifecycle.complete_success(message=message)
        if await self._restart_scheduler.schedule():
            return
        self._tracker.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self._tracker.log("Automatic backend restart scheduling failed")
