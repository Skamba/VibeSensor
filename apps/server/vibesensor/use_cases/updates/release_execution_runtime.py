"""Release-execution runtime assembly for updater workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.runtime_config import UpdateRuntimeConfig
from vibesensor.use_cases.updates.status import (
    UpdateStatusTracker,
    UpdateTerminalStateReporter,
)
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor

__all__ = ["build_update_workflow_executor"]

ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240
UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"


def build_update_workflow_executor(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    reporter: UpdateTerminalStateReporter,
    config: UpdateRuntimeConfig,
) -> UpdateWorkflowExecutor:
    """Build the canonical release-execution boundary for one updater workflow."""

    firmware_refresher = FirmwareRefresher(
        commands=commands,
        status=status,
        repo=config.repo,
        timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
    )
    installer = UpdateInstaller(
        commands=commands,
        status=status,
        config=config.installer_config,
    )
    return UpdateWorkflowExecutor(
        completion=UpdateCompletionCoordinator(
            restart_scheduler=UpdateRestartScheduler(
                commands=commands,
                status=status,
                service_name=UPDATE_SERVICE_NAME,
                restart_unit=UPDATE_RESTART_UNIT,
            ),
            reporter=reporter,
            status=status,
        ),
        stager=ServerReleaseStager(
            status=status,
            rollback_dir=config.rollback_dir,
        ),
        deployment=UpdateReleaseDeploymentCoordinator(
            installer=installer,
            firmware_refresher=firmware_refresher,
            status=status,
        ),
        firmware_refresher=firmware_refresher,
    )
