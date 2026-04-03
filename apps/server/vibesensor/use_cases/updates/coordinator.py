"""Canonical update workflow orchestration boundary."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.use_cases.updates.models import UpdateExecutionOutcome, UpdateRequest
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor


class UpdateCoordinator:
    """Own top-level sequencing while delegating planning and execution elsewhere."""

    __slots__ = (
        "_cancel_requested",
        "_preparation",
        "_release_planner",
        "_workflow_executor",
    )

    def __init__(
        self,
        *,
        preparation: UpdatePreparationCoordinator,
        release_planner: UpdateReleasePlanner,
        workflow_executor: UpdateWorkflowExecutor,
        cancel_requested: Callable[[], bool],
    ) -> None:
        self._preparation = preparation
        self._release_planner = release_planner
        self._workflow_executor = workflow_executor
        self._cancel_requested = cancel_requested

    async def execute(self, request: UpdateRequest) -> UpdateExecutionOutcome:
        prepared = await self._preparation.prepare(request)
        if prepared is None:
            return UpdateExecutionOutcome.aborted
        if self._cancelled():
            return UpdateExecutionOutcome.aborted
        plan = await self._release_planner.plan(prepared.current_version)
        if plan is None or self._cancelled():
            return UpdateExecutionOutcome.aborted
        return await self._workflow_executor.execute(
            plan,
            transport_session=prepared.transport_session,
        )

    def _cancelled(self) -> bool:
        return self._cancel_requested()
