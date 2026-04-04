"""Canonical request-scoped update workflow orchestration."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from vibesensor.shared.exceptions import UpdateCleanupError
from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.run_models import PreparedUpdateRun
from vibesensor.use_cases.updates.runtime_refresh import UpdateRuntimeDetailsRefresher
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor

__all__ = ["UpdateWorkflow"]


@dataclass(frozen=True, slots=True)
class UpdateWorkflow:
    """Run one update request through the canonical workflow lifecycle."""

    preparation: UpdatePreparationCoordinator
    release_planner: UpdateReleasePlanner
    workflow_executor: UpdateWorkflowExecutor
    transport_coordinator: UpdateTransportCoordinator
    runtime_details_refresher: UpdateRuntimeDetailsRefresher

    async def run(
        self,
        *,
        request: UpdateRequest,
    ) -> None:
        prepared: PreparedUpdateRun | None = None
        try:
            prepared = await self.preparation.prepare(request)
            planned = await self.release_planner.plan(prepared)
            await self.workflow_executor.execute(planned)
        finally:
            await self._finalize(prepared)

    async def _finalize(self, prepared: PreparedUpdateRun | None) -> None:
        active_error = sys.exc_info()[1]
        try:
            await self.transport_coordinator.cleanup_after_update(
                None if prepared is None else prepared.transport_session,
            )
            await self.runtime_details_refresher.refresh()
        except asyncio.CancelledError:
            raise
        except UpdateCleanupError as exc:
            if active_error is None:
                raise
            if isinstance(active_error, asyncio.CancelledError):
                raise UpdateCleanupError(f"Cleanup failed after cancellation: {exc}") from exc
            active_error.add_note(f"Cleanup also failed: {exc}")
