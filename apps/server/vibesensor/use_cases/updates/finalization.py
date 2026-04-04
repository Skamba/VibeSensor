"""Always-run workflow finalization for updater runs."""

from __future__ import annotations

import asyncio
import sys

from vibesensor.shared.exceptions import UpdateCleanupError
from vibesensor.use_cases.updates.runtime_refresh import UpdateRuntimeDetailsRefresher
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport_lifecycles import PreparedUpdateTransport

__all__ = ["UpdateWorkflowFinalizer"]


class UpdateWorkflowFinalizer:
    """Own unconditional transport cleanup and runtime refresh after one run."""

    __slots__ = ("_runtime_details_refresher", "_transport_coordinator")

    def __init__(
        self,
        *,
        transport_coordinator: UpdateTransportCoordinator,
        runtime_details_refresher: UpdateRuntimeDetailsRefresher,
    ) -> None:
        self._transport_coordinator = transport_coordinator
        self._runtime_details_refresher = runtime_details_refresher

    async def finalize(self, prepared_transport: PreparedUpdateTransport | None) -> None:
        active_error = sys.exc_info()[1]
        try:
            await self._transport_coordinator.cleanup_after_update(prepared_transport)
            await self._runtime_details_refresher.refresh()
        except asyncio.CancelledError:
            raise
        except UpdateCleanupError as exc:
            if active_error is None:
                raise
            if isinstance(active_error, asyncio.CancelledError):
                raise UpdateCleanupError(f"Cleanup failed after cancellation: {exc}") from exc
            active_error.add_note(f"Cleanup also failed: {exc}")
