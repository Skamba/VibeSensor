"""Workflow-focused updater runtime assembly."""

from __future__ import annotations

import logging

from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_execution_runtime import (
    build_update_workflow_executor,
)
from vibesensor.use_cases.updates.release_planning_runtime import (
    build_update_release_planner,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.runtime_config import UpdateRuntimeConfig
from vibesensor.use_cases.updates.runtime_core import UpdateRuntimeCore
from vibesensor.use_cases.updates.runtime_refresh import UpdateRuntimeDetailsRefresher
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.runtime import UpdateTransportRuntime
from vibesensor.use_cases.updates.workflow import UpdateWorkflow

__all__ = ["build_update_workflow"]


def build_update_workflow(
    *,
    core: UpdateRuntimeCore,
    config: UpdateRuntimeConfig,
    transport: UpdateTransportRuntime,
    logger: logging.Logger,
) -> UpdateWorkflow:
    return UpdateWorkflow(
        preparation=_build_preparation(
            commands=core.commands,
            status=core.status,
            transport=transport,
            config=config,
        ),
        release_planner=build_update_release_planner(
            status=core.status,
            config=config,
        ),
        workflow_executor=build_update_workflow_executor(
            commands=core.commands,
            status=core.status,
            reporter=core.reporter,
            config=config,
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
        current_version_provider=_current_version_provider,
    )


def _current_version_provider() -> str:
    from vibesensor import __version__ as current_version

    return current_version
