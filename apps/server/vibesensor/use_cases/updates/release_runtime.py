"""Release-focused updater runtime assembly."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.runtime_config import UpdateRuntimeConfig
from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["UpdateReleaseRuntime", "build_update_release_runtime"]

ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240
UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"


@dataclass(frozen=True, slots=True)
class UpdateReleaseRuntime:
    resolver: ServerReleaseResolver
    stager: ServerReleaseStager
    deployment: UpdateReleaseDeploymentCoordinator
    firmware_refresher: FirmwareRefresher
    restart_scheduler: UpdateRestartScheduler


def build_update_release_runtime(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    config: UpdateRuntimeConfig,
) -> UpdateReleaseRuntime:
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
    return UpdateReleaseRuntime(
        resolver=ServerReleaseResolver(
            rollback_dir=config.rollback_dir,
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
        restart_scheduler=UpdateRestartScheduler(
            commands=commands,
            status=status,
            service_name=UPDATE_SERVICE_NAME,
            restart_unit=UPDATE_RESTART_UNIT,
        ),
    )
