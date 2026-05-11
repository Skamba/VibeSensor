"""Execute the canonical install path for one discovered server release."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.run_models import InstallServerReleasePlan, PlannedUpdateRun

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["ServerReleaseExecutionCoordinator"]


class ServerReleaseExecutionCoordinator:
    """Own staged release download, firmware refresh policy, deployment, and success."""

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
        firmware_refresher: FirmwareRefresher,
        deployment: UpdateReleaseDeploymentCoordinator,
        status: UpdateStatusTracker,
    ) -> None:
        self._completion = completion
        self._stager = stager
        self._firmware_refresher = firmware_refresher
        self._deployment = deployment
        self._status = status

    async def execute(
        self,
        workflow: PlannedUpdateRun,
        plan: InstallServerReleasePlan,
    ) -> UpdateExecutionOutcome:
        release = plan.release
        async with self._stager.stage(release) as staged_release:
            refresh_result = await self._firmware_refresher.refresh_esp_firmware(
                pinned_tag=staged_release.release.tag,
            )
            if not refresh_result.succeeded:
                self._status.add_issue(
                    refresh_result.phase,
                    refresh_result.message,
                    refresh_result.detail,
                )
                self._status.log(
                    "ESP firmware refresh failed; continuing with existing cache",
                )
            await self._deployment.deploy(staged_release)
        await self._completion.complete_success(
            workflow.prepared.prepared_transport,
            message="Update completed successfully",
        )
        return UpdateExecutionOutcome.installed
