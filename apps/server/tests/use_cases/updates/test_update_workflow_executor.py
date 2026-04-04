from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
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
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    stager = MagicMock()
    deployer = MagicMock()
    deployer.deploy = AsyncMock(return_value=True)
    firmware_refresher = MagicMock()
    firmware_refresher.refresh_esp_firmware = AsyncMock()
    restart_scheduler = MagicMock()
    restart_scheduler.schedule = AsyncMock(return_value=True)
    status = MagicMock()
    transport_coordinator = MagicMock()
    transport_coordinator.complete_success = AsyncMock(return_value=True)
    executor = UpdateWorkflowExecutor(
        stager=stager,
        deployer=deployer,
        firmware_refresher=firmware_refresher,
        restart_scheduler=restart_scheduler,
        status=status,
        transport_coordinator=transport_coordinator,
    )
    return (
        executor,
        stager,
        deployer,
        firmware_refresher,
        restart_scheduler,
        status,
        transport_coordinator,
    )


def _prepared_run(session: object) -> PreparedUpdateRun:
    return PreparedUpdateRun(
        current_version="2026.4.3",
        transport_session=session,
    )


@pytest.mark.asyncio
async def test_execute_refresh_plan_refreshes_firmware_then_finalizes_transport() -> None:
    (
        executor,
        stager,
        deployer,
        firmware_refresher,
        restart_scheduler,
        status,
        transport_coordinator,
    ) = _executor()
    transport_session = object()
    workflow = PlannedUpdateRun(
        prepared=_prepared_run(transport_session),
        execution_plan=RefreshFirmwarePlan(
            latest_tag="server-v2026.4.3",
        ),
    )

    completed = await executor.execute(workflow)

    assert completed == UpdateExecutionOutcome.refresh_only
    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.3",
    )
    transport_coordinator.complete_success.assert_awaited_once_with(
        transport_session,
        message="No server update needed; ESP firmware checked",
    )
    restart_scheduler.schedule.assert_awaited_once_with()
    status.add_issue.assert_not_called()
    deployer.deploy.assert_not_awaited()
    assert not stager.stage.called


@pytest.mark.asyncio
async def test_execute_install_plan_stages_and_deploys_before_finalization(tmp_path: Path) -> None:
    (
        executor,
        stager,
        deployer,
        firmware_refresher,
        restart_scheduler,
        status,
        transport_coordinator,
    ) = _executor()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    transport_session = object()

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage

    completed = await executor.execute(
        workflow := PlannedUpdateRun(
            prepared=_prepared_run(transport_session),
            execution_plan=InstallServerReleasePlan(
                release=release,
            ),
        ),
    )

    assert completed == UpdateExecutionOutcome.installed
    stager.stage.assert_called_once_with(release)
    deployer.deploy.assert_awaited_once_with(staged_release)
    transport_coordinator.complete_success.assert_awaited_once_with(
        workflow.prepared.transport_session,
        message="Update completed successfully",
    )
    restart_scheduler.schedule.assert_awaited_once_with()
    status.add_issue.assert_not_called()
    firmware_refresher.refresh_esp_firmware.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_install_plan_propagates_deploy_failure_before_finalization(
    tmp_path: Path,
) -> None:
    (
        executor,
        stager,
        deployer,
        _firmware_refresher,
        restart_scheduler,
        _status,
        transport_coordinator,
    ) = _executor()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    transport_session = object()

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage
    deployer.deploy.side_effect = UpdateReleaseError("install failed")

    with pytest.raises(UpdateReleaseError, match="install failed"):
        await executor.execute(
            PlannedUpdateRun(
                prepared=_prepared_run(transport_session),
                execution_plan=InstallServerReleasePlan(
                    release=release,
                ),
            ),
        )

    deployer.deploy.assert_awaited_once_with(staged_release)
    transport_coordinator.complete_success.assert_not_awaited()
    restart_scheduler.schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_records_issue_when_restart_scheduling_fails() -> None:
    (
        executor,
        _stager,
        _deployer,
        firmware_refresher,
        restart_scheduler,
        status,
        transport_coordinator,
    ) = _executor()
    restart_scheduler.schedule.return_value = False
    transport_session = object()

    completed = await executor.execute(
        PlannedUpdateRun(
            prepared=_prepared_run(transport_session),
            execution_plan=RefreshFirmwarePlan(
                latest_tag="server-v2026.4.3",
            ),
        ),
    )

    assert completed == UpdateExecutionOutcome.refresh_only
    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.3",
    )
    transport_coordinator.complete_success.assert_awaited_once_with(
        transport_session,
        message="No server update needed; ESP firmware checked",
    )
    status.add_issue.assert_called_once_with(
        "done",
        "Backend restart was not scheduled automatically",
        "Run 'sudo systemctl restart vibesensor.service' manually",
    )
    status.log.assert_called_once_with("Automatic backend restart scheduling failed")
