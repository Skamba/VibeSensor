"""Canonical update workflow orchestration boundary."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import UpdateExecutionOutcome, UpdateRequest
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor


class UpdateCoordinator:
    """Own top-level sequencing while delegating planning and execution elsewhere."""

    __slots__ = ("_preparation", "_release_planner", "_workflow_executor")

    def __init__(
        self,
        *,
        preparation: UpdatePreparationCoordinator,
        release_planner: UpdateReleasePlanner,
        workflow_executor: UpdateWorkflowExecutor,
    ) -> None:
        self._preparation = preparation
        self._release_planner = release_planner
        self._workflow_executor = workflow_executor

    async def execute(self, request: UpdateRequest) -> UpdateExecutionOutcome:
        prepared = await self._preparation.prepare(request)
        plan = await self._release_planner.plan(prepared.current_version)
        return await self._workflow_executor.execute(plan)
