"""Release-execution boundary for update workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.run_models import (
    InstallServerReleasePlan,
    PlannedUpdateRun,
    RefreshFirmwarePlan,
)
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_lifecycles import PreparedUpdateTransport

__all__ = ["UpdateWorkflowExecutor"]


class UpdateWorkflowExecutor:
    """Execute a prepared release plan while delegating side effects to focused collaborators."""

    __slots__ = (
        "_deployment",
        "_firmware_refresher",
        "_restart_scheduler",
        "_stager",
        "_status",
    )

    def __init__(
        self,
        *,
        stager: ServerReleaseStager,
        deployment: UpdateReleaseDeploymentCoordinator,
        firmware_refresher: FirmwareRefresher,
        restart_scheduler: UpdateRestartScheduler,
        status: UpdateStatusTracker,
    ) -> None:
        self._stager = stager
        self._deployment = deployment
        self._firmware_refresher = firmware_refresher
        self._restart_scheduler = restart_scheduler
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
        await self._firmware_refresher.refresh_esp_firmware(pinned_tag=plan.latest_tag)
        await self._complete_success(
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
        await self._complete_success(
            workflow.prepared.prepared_transport,
            message="Update completed successfully",
        )
        return UpdateExecutionOutcome.installed

    async def _complete_success(
        self,
        prepared_transport: PreparedUpdateTransport,
        *,
        message: str,
    ) -> None:
        await prepared_transport.complete_success(message)
        if await self._restart_scheduler.schedule():
            return
        self._status.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self._status.log("Automatic backend restart scheduling failed")
