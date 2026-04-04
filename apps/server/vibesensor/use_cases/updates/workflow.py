"""Canonical request-scoped update workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor
from vibesensor.use_cases.updates.workflow_runner import UpdateWorkflowContext

__all__ = ["UpdateWorkflow"]


@dataclass(frozen=True, slots=True)
class UpdateWorkflow:
    """Run one canonical update request through preparation, planning, and execution."""

    preparation: UpdatePreparationCoordinator
    release_planner: UpdateReleasePlanner
    workflow_executor: UpdateWorkflowExecutor

    async def run(
        self,
        *,
        context: UpdateWorkflowContext,
        request: UpdateRequest,
    ) -> None:
        prepared = await self.preparation.prepare(request)
        context.transport = prepared.transport
        planned = await self.release_planner.plan(prepared)
        await self.workflow_executor.execute(planned)
