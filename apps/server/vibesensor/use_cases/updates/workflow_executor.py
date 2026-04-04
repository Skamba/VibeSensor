"""Release-execution boundary for update workflows."""

from __future__ import annotations

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.run_models import (
    InstallServerReleasePlan,
    PlannedUpdateRun,
    RefreshFirmwarePlan,
)
from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["UpdateWorkflowExecutor"]


class UpdateWorkflowExecutor:
    """Execute a prepared release plan while delegating side effects to focused collaborators."""

    __slots__ = (
        "_completion",
        "_deployment",
        "_firmware_refresher",
        "_stager",
        "_status",
    )

    def __init__(
        self,
        *,
        completion: UpdateCompletionCoordinator,
        stager: ServerReleaseStager,
        deployment: UpdateReleaseDeploymentCoordinator,
        firmware_refresher: FirmwareRefresher,
        status: UpdateStatusTracker,
    ) -> None:
        self._completion = completion
        self._stager = stager
        self._deployment = deployment
        self._firmware_refresher = firmware_refresher
        self._status = status

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
        refresh_result = await self._firmware_refresher.refresh_esp_firmware(
            pinned_tag=plan.latest_tag,
        )
        if not refresh_result.succeeded:
            self._status.fail(
                refresh_result.phase,
                refresh_result.message,
                refresh_result.detail,
                log_message="ESP firmware refresh failed; refresh-only update did not complete",
            )
            raise UpdateReleaseError(refresh_result.message)
        await self._completion.complete_success(
            workflow.prepared.prepared_transport,
            message="No server update needed; ESP firmware checked",
        )
        return UpdateExecutionOutcome.refresh_only

    async def _execute_install(
        self,
        *,
        workflow: PlannedUpdateRun,
        plan: InstallServerReleasePlan,
    ) -> UpdateExecutionOutcome:
        async with self._stager.stage(plan.release) as staged_release:
            await self._deployment.deploy(staged_release)
        await self._completion.complete_success(
            workflow.prepared.prepared_transport,
            message="Update completed successfully",
        )
        return UpdateExecutionOutcome.installed
