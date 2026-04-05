"""Release-execution boundary for update workflows."""

from __future__ import annotations

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
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
    """Execute a prepared release plan while delegating side effects to focused collaborators."""

    __slots__ = ("_completion", "_firmware_refresher", "_server_release_execution")

    def __init__(
        self,
        *,
        completion: UpdateCompletionCoordinator,
        server_release_execution: ServerReleaseExecutionCoordinator,
        firmware_refresher: FirmwareRefresher,
    ) -> None:
        self._completion = completion
        self._server_release_execution = server_release_execution
        self._firmware_refresher = firmware_refresher

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
            raise UpdateReleaseError(
                refresh_result.message,
                phase=refresh_result.phase,
                detail=refresh_result.detail,
                log_message="ESP firmware refresh failed; refresh-only update did not complete",
            )
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
        await self._server_release_execution.execute(plan.release)
        await self._completion.complete_success(
            workflow.prepared.prepared_transport,
            message="Update completed successfully",
        )
        return UpdateExecutionOutcome.installed
