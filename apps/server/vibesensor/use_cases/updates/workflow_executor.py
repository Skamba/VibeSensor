"""Execution dispatcher for planned update workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.firmware_refresh_execution import (
    RefreshFirmwareExecutionCoordinator,
)
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome
from vibesensor.use_cases.updates.run_models import (
    InstallServerReleasePlan,
    PlannedUpdateRun,
    RefreshFirmwarePlan,
)
from vibesensor.use_cases.updates.server_release_execution import (
    ServerReleaseExecutionCoordinator,
)

__all__ = ["UpdateWorkflowExecutor"]


class UpdateWorkflowExecutor:
    """Dispatch a prepared release plan to the focused execution collaborator."""

    __slots__ = ("_refresh_execution", "_server_release_execution")

    def __init__(
        self,
        *,
        refresh_execution: RefreshFirmwareExecutionCoordinator,
        server_release_execution: ServerReleaseExecutionCoordinator,
    ) -> None:
        self._refresh_execution = refresh_execution
        self._server_release_execution = server_release_execution

    async def execute(
        self,
        workflow: PlannedUpdateRun,
    ) -> UpdateExecutionOutcome:
        plan = workflow.execution_plan
        if isinstance(plan, RefreshFirmwarePlan):
            return await self._execute_refresh_only(
                workflow=workflow,
                plan=plan,
            )
        return await self._execute_install(
            workflow=workflow,
            plan=plan,
        )

    async def _execute_refresh_only(
        self,
        *,
        workflow: PlannedUpdateRun,
        plan: RefreshFirmwarePlan,
    ) -> UpdateExecutionOutcome:
        return await self._refresh_execution.execute(workflow, plan)

    async def _execute_install(
        self,
        *,
        workflow: PlannedUpdateRun,
        plan: InstallServerReleasePlan,
    ) -> UpdateExecutionOutcome:
        return await self._server_release_execution.execute(workflow, plan)
