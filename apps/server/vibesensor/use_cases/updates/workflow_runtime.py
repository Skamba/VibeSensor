"""Workflow-focused updater runtime assembly."""

from __future__ import annotations

import logging

from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.release_runtime import UpdateReleaseRuntime
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.runtime_config import UpdateRuntimeConfig
from vibesensor.use_cases.updates.runtime_core import UpdateRuntimeCore
from vibesensor.use_cases.updates.runtime_refresh import UpdateRuntimeDetailsRefresher
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.runtime import UpdateTransportRuntime
from vibesensor.use_cases.updates.workflow import UpdateWorkflow
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor

__all__ = ["build_update_workflow"]


def build_update_workflow(
    *,
    core: UpdateRuntimeCore,
    config: UpdateRuntimeConfig,
    transport: UpdateTransportRuntime,
    release: UpdateReleaseRuntime,
    logger: logging.Logger,
) -> UpdateWorkflow:
    return UpdateWorkflow(
        preparation=_build_preparation(
            commands=core.commands,
            status=core.status,
            transport=transport,
            config=config,
        ),
        release_planner=UpdateReleasePlanner(
            status=core.status,
            resolver=release.resolver,
        ),
        workflow_executor=UpdateWorkflowExecutor(
            completion=UpdateCompletionCoordinator(
                restart_scheduler=release.restart_scheduler,
                status=core.status,
            ),
            stager=release.stager,
            deployment=release.deployment,
            firmware_refresher=release.firmware_refresher,
            status=core.status,
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
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    transport: UpdateTransportRuntime,
    config: UpdateRuntimeConfig,
) -> UpdatePreparationCoordinator:
    return UpdatePreparationCoordinator(
        status=status,
        commands=commands,
        transport_coordinator=transport.coordinator,
        validation_config=config.validation_config,
        current_version_provider=_current_version_provider,
    )


def _current_version_provider() -> str:
    from vibesensor import __version__ as current_version

    return current_version
