"""Startup recovery coordination for interrupted updater runs."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import UpdateState
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator

__all__ = ["UpdateStartupRecoveryCoordinator"]


class UpdateStartupRecoveryCoordinator:
    """Recover transport-owned updater state after an interrupted server restart."""

    __slots__ = ("_status", "_transport_coordinator")

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        transport_coordinator: UpdateTransportCoordinator,
    ) -> None:
        self._status = status
        self._transport_coordinator = transport_coordinator

    async def recover(self) -> None:
        status = self._status.status
        if status.state != UpdateState.running or status.finished_at is not None:
            return
        self._status.mark_interrupted("Update interrupted by server restart")
        await self._transport_coordinator.recover_interrupted(status)
