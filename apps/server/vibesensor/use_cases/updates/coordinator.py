"""Canonical update workflow orchestration boundary."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.use_cases.updates.models import (
    UpdateExecutionOutcome,
    UpdateRequest,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_controller import UpdateTransportController
from vibesensor.use_cases.updates.validation import validate_prerequisites
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor


class UpdateCoordinator:
    """Own top-level sequencing while delegating planning and execution elsewhere."""

    __slots__ = (
        "_cancel_requested",
        "_commands",
        "_release_planner",
        "_tracker",
        "_transport_controller",
        "_validation_config",
        "_workflow_executor",
    )

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        commands: UpdateCommandExecutor,
        transport_controller: UpdateTransportController,
        release_planner: UpdateReleasePlanner,
        workflow_executor: UpdateWorkflowExecutor,
        cancel_requested: Callable[[], bool],
        validation_config: UpdateValidationConfig,
    ) -> None:
        self._tracker = tracker
        self._commands = commands
        self._transport_controller = transport_controller
        self._release_planner = release_planner
        self._workflow_executor = workflow_executor
        self._cancel_requested = cancel_requested
        self._validation_config = validation_config

    async def execute(self, request: UpdateRequest) -> UpdateExecutionOutcome:
        if not await self._validate(request):
            return UpdateExecutionOutcome.aborted
        transport_session = await self._transport_controller.prepare(request)
        if transport_session is None or self._cancelled():
            return UpdateExecutionOutcome.aborted

        from vibesensor import __version__ as current_version

        plan = await self._release_planner.plan(current_version)
        if plan is None or self._cancelled():
            return UpdateExecutionOutcome.aborted
        return await self._workflow_executor.execute(plan, transport_session=transport_session)

    async def _validate(self, request: UpdateRequest) -> bool:
        if not await validate_prerequisites(
            commands=self._commands,
            tracker=self._tracker,
            config=self._validation_config,
            request=request,
        ):
            return False
        return not self._cancelled()

    def _cancelled(self) -> bool:
        return self._cancel_requested()
