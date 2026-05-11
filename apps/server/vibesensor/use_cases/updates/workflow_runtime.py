"""Workflow-focused updater runtime assembly."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.firmware_refresh_execution import (
    RefreshFirmwareExecutionCoordinator,
)
from vibesensor.use_cases.updates.installer import UpdateInstaller
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.releases.release_fetcher import ServerReleaseFetcher
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.runtime_config import UpdateRuntimeConfig
from vibesensor.use_cases.updates.runtime_core import UpdateRuntimeCore
from vibesensor.use_cases.updates.runtime_refresh import UpdateRuntimeDetailsRefresher
from vibesensor.use_cases.updates.server_release_execution import (
    ServerReleaseExecutionCoordinator,
)
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.runtime import UpdateTransportRuntime
from vibesensor.use_cases.updates.workflow import UpdateWorkflow
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor
from vibesensor.use_cases.updates.workflow_planner import UpdateWorkflowPlanner

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.status import UpdateTerminalStateReporter

__all__ = ["build_update_workflow"]


def build_update_workflow(
    *,
    core: UpdateRuntimeCore,
    config: UpdateRuntimeConfig,
    transport: UpdateTransportRuntime,
    logger: logging.Logger,
    server_release_fetcher: ServerReleaseFetcher | None = None,
) -> UpdateWorkflow:
    release_fetcher = server_release_fetcher or ServerReleaseFetcher(
        config.release_fetcher_config,
    )
    return UpdateWorkflow(
        planner=UpdateWorkflowPlanner(
            preparation=_build_preparation(
                commands=core.commands,
                status=core.status,
                transport=transport,
                config=config,
            ),
            release_planner=UpdateReleasePlanner(
                status=core.status,
                current_version_provider=core.current_version_provider,
                resolver=ServerReleaseResolver(
                    release_fetcher=release_fetcher,
                ),
            ),
        ),
        workflow_executor=_build_workflow_executor(
            commands=core.commands,
            status=core.status,
            reporter=core.reporter,
            config=config,
            release_fetcher=release_fetcher,
        ),
        finalizer=UpdateWorkflowFinalizer(
            transport_coordinator=transport.coordinator,
            runtime_details_refresher=UpdateRuntimeDetailsRefresher(
                status=core.status,
                repo=config.repo,
                logger=logger,
            ),
        ),
    )


def _build_preparation(
    *,
    transport: UpdateTransportRuntime,
    config: UpdateRuntimeConfig,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
) -> UpdatePreparationCoordinator:
    return UpdatePreparationCoordinator(
        status=status,
        commands=commands,
        transport_coordinator=transport.coordinator,
        validation_config=config.validation_config,
    )


def _build_workflow_executor(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    reporter: UpdateTerminalStateReporter,
    config: UpdateRuntimeConfig,
    release_fetcher: ServerReleaseFetcher,
) -> UpdateWorkflowExecutor:
    execution_config = config.execution_config
    firmware_refresher = FirmwareRefresher(
        commands=commands,
        status=status,
        repo=config.repo,
        timeout_s=execution_config.firmware_refresh_timeout_s,
    )
    completion = UpdateCompletionCoordinator(
        restart_scheduler=UpdateRestartScheduler(
            commands=commands,
            status=status,
            service_name=execution_config.service_name,
            restart_unit=execution_config.restart_unit,
        ),
        reporter=reporter,
        status=status,
    )
    installer = UpdateInstaller(
        commands=commands,
        status=status,
        config=config.installer_config,
    )
    return UpdateWorkflowExecutor(
        refresh_execution=RefreshFirmwareExecutionCoordinator(
            completion=completion,
            firmware_refresher=firmware_refresher,
        ),
        server_release_execution=ServerReleaseExecutionCoordinator(
            completion=completion,
            stager=ServerReleaseStager(
                status=status,
                release_fetcher=release_fetcher,
            ),
            firmware_refresher=firmware_refresher,
            deployment=UpdateReleaseDeploymentCoordinator(
                installer=installer,
                status=status,
            ),
            status=status,
        ),
    )
