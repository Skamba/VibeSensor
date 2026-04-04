"""Successful update completion boundary for updater workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.status import (
    UpdateStatusTracker,
    UpdateTerminalStateReporter,
)
from vibesensor.use_cases.updates.transport.lifecycles import PreparedUpdateTransport

__all__ = ["UpdateCompletionCoordinator"]


class UpdateCompletionCoordinator:
    """Own post-success transport completion and restart follow-up."""

    __slots__ = ("_reporter", "_restart_scheduler", "_status")

    def __init__(
        self,
        *,
        restart_scheduler: UpdateRestartScheduler,
        reporter: UpdateTerminalStateReporter,
        status: UpdateStatusTracker,
    ) -> None:
        self._reporter = reporter
        self._restart_scheduler = restart_scheduler
        self._status = status

    async def complete_success(
        self,
        prepared_transport: PreparedUpdateTransport,
        *,
        message: str,
    ) -> None:
        await prepared_transport.complete_success()
        self._reporter.mark_success(message)
        if not await self._restart_scheduler.schedule():
            self._status.add_issue(
                "done",
                "Backend restart was not scheduled automatically",
                "Run 'sudo systemctl restart vibesensor.service' manually",
            )
            self._status.log("Automatic backend restart scheduling failed")
