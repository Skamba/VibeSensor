from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.firmware import FirmwareRefreshResult
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome, UpdatePhase
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
]:
    completion = MagicMock()
    completion.complete_success = AsyncMock()
    stager = MagicMock()
    deployment = MagicMock()
    deployment.deploy = AsyncMock(return_value=True)
    firmware_refresher = MagicMock()
    firmware_refresher.refresh_esp_firmware = AsyncMock(
        return_value=FirmwareRefreshResult.success(),
    )
    executor = UpdateWorkflowExecutor(
        completion=completion,
        stager=stager,
        deployment=deployment,
        firmware_refresher=firmware_refresher,
    )
    return (
        executor,
        completion,
        stager,
        deployment,
        firmware_refresher,
    )


def _prepared_run(prepared_transport: object) -> PreparedUpdateRun:
    return PreparedUpdateRun(
        current_version="2026.4.3",
        prepared_transport=prepared_transport,
    )


@pytest.mark.asyncio
async def test_execute_refresh_plan_refreshes_firmware_then_completes_success() -> None:
    (
        executor,
        completion,
        stager,
        deployment,
        firmware_refresher,
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
    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.3",
    )
    completion.complete_success.assert_awaited_once_with(
        prepared_transport,
        message="No server update needed; ESP firmware checked",
    )
    deployment.deploy.assert_not_awaited()
    assert not stager.stage.called


@pytest.mark.asyncio
async def test_execute_refresh_plan_fails_when_firmware_refresh_fails() -> None:
    (
        executor,
        completion,
        stager,
        deployment,
        firmware_refresher,
    ) = _executor()
    prepared_transport = MagicMock()
    workflow = PlannedUpdateRun(
        prepared=_prepared_run(prepared_transport),
        execution_plan=RefreshFirmwarePlan(
            latest_tag="server-v2026.4.3",
        ),
    )
    firmware_refresher.refresh_esp_firmware.return_value = FirmwareRefreshResult.failure(
        message="ESP firmware cache refresh failed (exit 1)",
        detail="cache unavailable",
    )

    with pytest.raises(UpdateReleaseError, match="ESP firmware cache refresh failed") as excinfo:
        await executor.execute(workflow)

    assert excinfo.value.phase == UpdatePhase.downloading.value
    assert excinfo.value.detail == "cache unavailable"
    assert (
        excinfo.value.log_message
        == "ESP firmware refresh failed; refresh-only update did not complete"
    )
    completion.complete_success.assert_not_awaited()
    deployment.deploy.assert_not_awaited()
    assert not stager.stage.called


@pytest.mark.asyncio
async def test_execute_install_plan_stages_and_deploys_before_completion(tmp_path: Path) -> None:
    (
        executor,
        completion,
        stager,
        deployment,
        firmware_refresher,
    ) = _executor()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    prepared_transport = MagicMock()

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage

    completed = await executor.execute(
        PlannedUpdateRun(
            prepared=_prepared_run(prepared_transport),
            execution_plan=InstallServerReleasePlan(
                release=release,
            ),
        ),
    )

    assert completed == UpdateExecutionOutcome.installed
    stager.stage.assert_called_once_with(release)
    deployment.deploy.assert_awaited_once_with(staged_release)
    completion.complete_success.assert_awaited_once_with(
        prepared_transport,
        message="Update completed successfully",
    )
    firmware_refresher.refresh_esp_firmware.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_install_plan_propagates_deploy_failure_before_completion(
    tmp_path: Path,
) -> None:
    (
        executor,
        completion,
        stager,
        deployment,
        _firmware_refresher,
    ) = _executor()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    prepared_transport = MagicMock()

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage
    deployment.deploy.side_effect = UpdateReleaseError("install failed")

    with pytest.raises(UpdateReleaseError, match="install failed"):
        await executor.execute(
            PlannedUpdateRun(
                prepared=_prepared_run(prepared_transport),
                execution_plan=InstallServerReleasePlan(
                    release=release,
                ),
            ),
        )

    deployment.deploy.assert_awaited_once_with(staged_release)
    completion.complete_success.assert_not_awaited()
