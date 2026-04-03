from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.use_cases.updates.release_planner import (
    InstallServerReleasePlan,
    RefreshFirmwarePlan,
)
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor


def _executor(
    *,
    cancel_requested=lambda: False,
) -> tuple[UpdateWorkflowExecutor, MagicMock, MagicMock, MagicMock, MagicMock]:
    stager = MagicMock()
    deployer = MagicMock()
    deployer.deploy = AsyncMock(return_value=True)
    firmware_refresher = MagicMock()
    firmware_refresher.refresh_esp_firmware = AsyncMock()
    finalizer = MagicMock()
    finalizer.complete = AsyncMock(return_value=True)
    executor = UpdateWorkflowExecutor(
        stager=stager,
        deployer=deployer,
        firmware_refresher=firmware_refresher,
        finalizer=finalizer,
        cancel_requested=cancel_requested,
    )
    return executor, stager, deployer, firmware_refresher, finalizer


@pytest.mark.asyncio
async def test_execute_refresh_plan_refreshes_firmware_then_finalizes_transport() -> None:
    executor, stager, deployer, firmware_refresher, finalizer = _executor()
    transport_session = object()
    plan = RefreshFirmwarePlan(
        current_version="2026.4.3",
        latest_tag="server-v2026.4.3",
    )

    completed = await executor.execute(plan, transport_session=transport_session)

    assert completed is True
    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.3",
    )
    finalizer.complete.assert_awaited_once_with(
        transport_session,
        message="No server update needed; ESP firmware checked",
    )
    deployer.deploy.assert_not_awaited()
    assert not stager.stage.called


@pytest.mark.asyncio
async def test_execute_install_plan_stages_and_deploys_before_finalization(tmp_path: Path) -> None:
    executor, stager, deployer, firmware_refresher, finalizer = _executor()
    transport_session = object()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage

    completed = await executor.execute(
        InstallServerReleasePlan(current_version="2026.4.3", release=release),
        transport_session=transport_session,
    )

    assert completed is True
    stager.stage.assert_called_once_with(release)
    deployer.deploy.assert_awaited_once_with(staged_release)
    finalizer.complete.assert_awaited_once_with(
        transport_session,
        message="Update completed successfully",
    )
    firmware_refresher.refresh_esp_firmware.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_install_plan_stops_before_finalization_when_cancelled(
    tmp_path: Path,
) -> None:
    cancel_results = iter((False, True))
    executor, stager, deployer, _firmware_refresher, finalizer = _executor(
        cancel_requested=lambda: next(cancel_results),
    )
    transport_session = object()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage

    completed = await executor.execute(
        InstallServerReleasePlan(current_version="2026.4.3", release=release),
        transport_session=transport_session,
    )

    assert completed is False
    deployer.deploy.assert_awaited_once_with(staged_release)
    finalizer.complete.assert_not_awaited()
