from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome
from vibesensor.use_cases.updates.run_models import (
    InstallServerReleasePlan,
    PlannedUpdateRun,
    PreparedUpdateRun,
    RefreshFirmwarePlan,
)
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor


def _executor() -> tuple[
    UpdateWorkflowExecutor,
    MagicMock,
    MagicMock,
]:
    refresh_execution = MagicMock()
    refresh_execution.execute = AsyncMock(return_value=UpdateExecutionOutcome.refresh_only)
    server_release_execution = MagicMock()
    server_release_execution.execute = AsyncMock(return_value=UpdateExecutionOutcome.installed)
    executor = UpdateWorkflowExecutor(
        refresh_execution=refresh_execution,
        server_release_execution=server_release_execution,
    )
    return (
        executor,
        refresh_execution,
        server_release_execution,
    )


def _prepared_run(prepared_transport: object) -> PreparedUpdateRun:
    return PreparedUpdateRun(
        prepared_transport=prepared_transport,
    )


@pytest.mark.asyncio
async def test_execute_refresh_plan_dispatches_to_refresh_execution() -> None:
    (
        executor,
        refresh_execution,
        server_release_execution,
    ) = _executor()
    prepared_transport = MagicMock()
    workflow = PlannedUpdateRun(
        prepared=_prepared_run(prepared_transport),
        execution_plan=RefreshFirmwarePlan(
            latest_tag="server-v2026.4.3",
        ),
    )

    completed = await executor.execute(workflow)

    assert completed == UpdateExecutionOutcome.refresh_only
    refresh_execution.execute.assert_awaited_once_with(workflow, workflow.execution_plan)
    server_release_execution.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_refresh_plan_propagates_refresh_execution_failure() -> None:
    (
        executor,
        refresh_execution,
        server_release_execution,
    ) = _executor()
    workflow = PlannedUpdateRun(
        prepared=_prepared_run(MagicMock()),
        execution_plan=RefreshFirmwarePlan(
            latest_tag="server-v2026.4.3",
        ),
    )
    refresh_execution.execute.side_effect = UpdateReleaseError("refresh failed")

    with pytest.raises(UpdateReleaseError, match="refresh failed"):
        await executor.execute(workflow)

    refresh_execution.execute.assert_awaited_once_with(workflow, workflow.execution_plan)
    server_release_execution.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_install_plan_dispatches_to_server_release_execution() -> None:
    (
        executor,
        refresh_execution,
        server_release_execution,
    ) = _executor()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    workflow = PlannedUpdateRun(
        prepared=_prepared_run(MagicMock()),
        execution_plan=InstallServerReleasePlan(
            release=release,
        ),
    )

    completed = await executor.execute(workflow)

    assert completed == UpdateExecutionOutcome.installed
    server_release_execution.execute.assert_awaited_once_with(workflow, workflow.execution_plan)
    refresh_execution.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_install_plan_propagates_release_execution_failure() -> None:
    (
        executor,
        refresh_execution,
        server_release_execution,
    ) = _executor()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    workflow = PlannedUpdateRun(
        prepared=_prepared_run(MagicMock()),
        execution_plan=InstallServerReleasePlan(
            release=release,
        ),
    )
    server_release_execution.execute.side_effect = UpdateReleaseError("install failed")

    with pytest.raises(UpdateReleaseError, match="install failed"):
        await executor.execute(workflow)

    server_release_execution.execute.assert_awaited_once_with(workflow, workflow.execution_plan)
    refresh_execution.execute.assert_not_awaited()
