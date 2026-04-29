"""Always-run workflow finalization for updater runs."""

from __future__ import annotations

import asyncio

from vibesensor.shared.exceptions import UpdateCleanupError
from vibesensor.use_cases.updates.runtime_refresh import UpdateRuntimeDetailsRefresher
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport.lifecycles import PreparedUpdateTransport

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

    async def finalize(
        self,
        prepared_transport: PreparedUpdateTransport | None,
        *,
        prior_error: BaseException | None = None,
    ) -> None:
        try:
            await self._transport_coordinator.cleanup_after_update(prepared_transport)
            await self._runtime_details_refresher.refresh()
        except UpdateCleanupError as exc:
            if prior_error is None:
                raise
            if isinstance(prior_error, asyncio.CancelledError):
                raise UpdateCleanupError(f"Cleanup failed after cancellation: {exc}") from exc
            prior_error.add_note(f"Cleanup also failed: {exc}")
