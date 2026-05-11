"""Request-scoped planning boundary for update workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.run_models import PlannedUpdateRun, PreparedUpdateRun

__all__ = ["UpdateWorkflowPlanner"]


@dataclass(frozen=True, slots=True)
class UpdateWorkflowPlanner:
    """Prepare transport and choose release work before side-effectful execution."""

    preparation: UpdatePreparationCoordinator
    release_planner: UpdateReleasePlanner

    async def plan(
        self,
        request: UpdateRequest,
        *,
        on_prepared: Callable[[PreparedUpdateRun], None] | None = None,
    ) -> PlannedUpdateRun:
        prepared = await self.preparation.prepare(request)
        if on_prepared is not None:
            on_prepared(prepared)
        return await self.release_planner.plan(prepared)
