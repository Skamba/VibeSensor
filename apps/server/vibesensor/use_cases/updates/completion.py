"""Success completion boundary for updater workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.status import UpdateStatusRecorder
from vibesensor.use_cases.updates.transport_coordinator import (
    PreparedUpdateTransport,
    UpdateTransportCoordinator,
)

__all__ = ["UpdateCompletionCoordinator"]


class UpdateCompletionCoordinator:
    """Finalize successful workflows after install/refresh work is done."""

    __slots__ = ("_restart_scheduler", "_status_recorder", "_transport_coordinator")

    def __init__(
        self,
        *,
        transport_coordinator: UpdateTransportCoordinator,
        status_recorder: UpdateStatusRecorder,
        restart_scheduler: UpdateRestartScheduler,
    ) -> None:
        self._transport_coordinator = transport_coordinator
        self._status_recorder = status_recorder
        self._restart_scheduler = restart_scheduler

    async def complete(
        self,
        transport: PreparedUpdateTransport,
        *,
        message: str,
    ) -> None:
        await self._transport_coordinator.complete_success(transport, message=message)
        if await self._restart_scheduler.schedule():
            return
        self._status_recorder.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self._status_recorder.log("Automatic backend restart scheduling failed")
