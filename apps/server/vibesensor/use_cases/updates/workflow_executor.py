"""Release-execution boundary for update workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome
from vibesensor.use_cases.updates.release_deployment import UpdateReleaseDeployer
from vibesensor.use_cases.updates.release_planner import (
    InstallServerReleasePlan,
    RefreshFirmwarePlan,
    ReleaseExecutionPlan,
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
        plan: ReleaseExecutionPlan,
    ) -> UpdateExecutionOutcome:
        if isinstance(plan, RefreshFirmwarePlan):
            return await self._execute_refresh_only(plan)
        return await self._execute_install(plan)

    async def _execute_refresh_only(
        self,
        plan: RefreshFirmwarePlan,
    ) -> UpdateExecutionOutcome:
        await self._firmware_refresher.refresh_esp_firmware(pinned_tag=plan.latest_tag)
        await self._finalizer.complete(message="No server update needed; ESP firmware checked")
        return UpdateExecutionOutcome.refresh_only

    async def _execute_install(
        self,
        plan: InstallServerReleasePlan,
    ) -> UpdateExecutionOutcome:
        async with self._stager.stage(plan.release) as staged_release:
            await self._deployer.deploy(staged_release)
        await self._finalizer.complete(message="Update completed successfully")
        return UpdateExecutionOutcome.installed
