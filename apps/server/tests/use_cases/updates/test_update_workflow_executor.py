from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.models import (
    UpdateExecutionOutcome,
    UpdateRequest,
    UpdateTransport,
)
from vibesensor.use_cases.updates.release_planner import (
    InstallServerReleasePlan,
    PlannedUpdateWorkflow,
    RefreshFirmwarePlan,
)
from vibesensor.use_cases.updates.transport_coordinator import PreparedUpdateTransport
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor


def _executor() -> tuple[UpdateWorkflowExecutor, MagicMock, MagicMock, MagicMock, MagicMock]:
    stager = MagicMock()
    deployer = MagicMock()
    deployer.deploy = AsyncMock(return_value=True)
    firmware_refresher = MagicMock()
    firmware_refresher.refresh_esp_firmware = AsyncMock()
    completion = MagicMock()
    completion.complete = AsyncMock(return_value=True)
    executor = UpdateWorkflowExecutor(
        stager=stager,
        deployer=deployer,
        firmware_refresher=firmware_refresher,
        completion=completion,
    )
    return executor, stager, deployer, firmware_refresher, completion


def _prepared_transport(session: object) -> PreparedUpdateTransport:
    return PreparedUpdateTransport(
        request=UpdateRequest(
            transport=UpdateTransport.usb_internet,
            ssid=None,
            password="",
        ),
        session=session,
    )


@pytest.mark.asyncio
async def test_execute_refresh_plan_refreshes_firmware_then_finalizes_transport() -> None:
    executor, stager, deployer, firmware_refresher, completion = _executor()
    transport_session = object()
    workflow = PlannedUpdateWorkflow(
        transport=_prepared_transport(transport_session),
        execution_plan=RefreshFirmwarePlan(
            current_version="2026.4.3",
            latest_tag="server-v2026.4.3",
        ),
    )

    completed = await executor.execute(workflow)

    assert completed == UpdateExecutionOutcome.refresh_only
    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.3",
    )
    completion.complete.assert_awaited_once_with(
        workflow.transport,
        message="No server update needed; ESP firmware checked",
    )
    deployer.deploy.assert_not_awaited()
    assert not stager.stage.called


@pytest.mark.asyncio
async def test_execute_install_plan_stages_and_deploys_before_finalization(tmp_path: Path) -> None:
    executor, stager, deployer, firmware_refresher, completion = _executor()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    transport_session = object()

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage

    completed = await executor.execute(
        workflow := PlannedUpdateWorkflow(
            transport=_prepared_transport(transport_session),
            execution_plan=InstallServerReleasePlan(
                current_version="2026.4.3",
                release=release,
            ),
        ),
    )

    assert completed == UpdateExecutionOutcome.installed
    stager.stage.assert_called_once_with(release)
    deployer.deploy.assert_awaited_once_with(staged_release)
    completion.complete.assert_awaited_once_with(
        workflow.transport,
        message="Update completed successfully",
    )
    firmware_refresher.refresh_esp_firmware.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_install_plan_propagates_deploy_failure_before_finalization(
    tmp_path: Path,
) -> None:
    executor, stager, deployer, _firmware_refresher, completion = _executor()
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
            PlannedUpdateWorkflow(
                transport=_prepared_transport(transport_session),
                execution_plan=InstallServerReleasePlan(
                    current_version="2026.4.3",
                    release=release,
                ),
            ),
        )

    deployer.deploy.assert_awaited_once_with(staged_release)
    completion.complete.assert_not_awaited()
