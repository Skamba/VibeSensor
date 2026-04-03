"""Release-execution boundary for update workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome
from vibesensor.use_cases.updates.release_deployment import UpdateReleaseDeployer
from vibesensor.use_cases.updates.release_planner import (
    InstallServerReleasePlan,
    PlannedUpdateWorkflow,
    RefreshFirmwarePlan,
)
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.success_finalizer import UpdateSuccessFinalizer

__all__ = ["UpdateWorkflowExecutor"]


class UpdateWorkflowExecutor:
    """Execute a prepared release plan while delegating side effects to focused collaborators."""

    __slots__ = ("_deployer", "_firmware_refresher", "_finalizer", "_stager")

    def __init__(
        self,
        *,
        stager: ServerReleaseStager,
        deployer: UpdateReleaseDeployer,
        firmware_refresher: FirmwareRefresher,
        finalizer: UpdateSuccessFinalizer,
    ) -> None:
        self._stager = stager
        self._deployer = deployer
        self._firmware_refresher = firmware_refresher
        self._finalizer = finalizer

    async def execute(
        self,
        workflow: PlannedUpdateWorkflow,
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
        workflow: PlannedUpdateWorkflow,
        plan: RefreshFirmwarePlan,
    ) -> UpdateExecutionOutcome:
        await self._firmware_refresher.refresh_esp_firmware(pinned_tag=plan.latest_tag)
        await self._finalizer.complete(
            workflow.transport_session,
            message="No server update needed; ESP firmware checked",
        )
        return UpdateExecutionOutcome.refresh_only

    async def _execute_install(
        self,
        *,
        workflow: PlannedUpdateWorkflow,
        plan: InstallServerReleasePlan,
    ) -> UpdateExecutionOutcome:
        async with self._stager.stage(plan.release) as staged_release:
            await self._deployer.deploy(staged_release)
        await self._finalizer.complete(
            workflow.transport_session,
            message="Update completed successfully",
        )
        return UpdateExecutionOutcome.installed
