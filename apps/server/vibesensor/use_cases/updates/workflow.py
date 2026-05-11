"""Canonical request-scoped update workflow orchestration."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer
from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.run_models import PreparedUpdateRun
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor
from vibesensor.use_cases.updates.workflow_planner import UpdateWorkflowPlanner

__all__ = ["UpdateWorkflow"]


@dataclass(frozen=True, slots=True)
class UpdateWorkflow:
    """Run one update request through the canonical workflow lifecycle."""

    planner: UpdateWorkflowPlanner
    workflow_executor: UpdateWorkflowExecutor
    finalizer: UpdateWorkflowFinalizer

    async def run(
        self,
        *,
        request: UpdateRequest,
    ) -> None:
        prepared: PreparedUpdateRun | None = None

        def remember_prepared(value: PreparedUpdateRun) -> None:
            nonlocal prepared
            prepared = value

        try:
            planned = await self.planner.plan(request, on_prepared=remember_prepared)
            await self.workflow_executor.execute(planned)
        finally:
            await self.finalizer.finalize(
                None if prepared is None else prepared.prepared_transport,
                prior_error=sys.exc_info()[1],
            )
