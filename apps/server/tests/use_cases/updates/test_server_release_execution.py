from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.use_cases.updates.firmware import FirmwareRefreshResult
from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.server_release_execution import (
    ServerReleaseExecutionCoordinator,
)


def _coordinator() -> tuple[
    ServerReleaseExecutionCoordinator,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    stager = MagicMock()
    firmware_refresher = MagicMock()
    firmware_refresher.refresh_esp_firmware = AsyncMock(
        return_value=FirmwareRefreshResult.success(),
    )
    deployment = MagicMock()
    deployment.deploy = AsyncMock(return_value=None)
    status = MagicMock()
    return (
        ServerReleaseExecutionCoordinator(
            stager=stager,
            firmware_refresher=firmware_refresher,
            deployment=deployment,
            status=status,
        ),
        stager,
        firmware_refresher,
        deployment,
        status,
    )


@pytest.mark.asyncio
async def test_execute_stages_refreshes_then_deploys(tmp_path: Path) -> None:
    coordinator, stager, firmware_refresher, deployment, _status = _coordinator()
    events: list[str] = []
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="a" * 64)
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")

    @asynccontextmanager
    async def stage(_release: object):
        events.append("stage")
        yield staged_release

    async def refresh_esp_firmware(*, pinned_tag: str) -> FirmwareRefreshResult:
        events.append(f"firmware:{pinned_tag}")
        return FirmwareRefreshResult.success()

    async def deploy(arg: object) -> None:
        events.append(f"deploy:{Path(arg.wheel_path).name}")

    stager.stage.side_effect = stage
    firmware_refresher.refresh_esp_firmware.side_effect = refresh_esp_firmware
    deployment.deploy.side_effect = deploy

    await coordinator.execute(release)

    assert events == [
        "stage",
        "firmware:server-v2026.4.4",
        "deploy:release.whl",
    ]


@pytest.mark.asyncio
async def test_execute_continues_when_firmware_refresh_fails(tmp_path: Path) -> None:
    coordinator, stager, firmware_refresher, deployment, status = _coordinator()
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4", sha256="a" * 64)
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage
    firmware_refresher.refresh_esp_firmware.return_value = FirmwareRefreshResult.failure(
        message="ESP firmware cache refresh failed (exit 1)",
        detail="cache unavailable",
    )

    await coordinator.execute(release)

    status.add_issue.assert_called_once_with(
        UpdatePhase.downloading,
        "ESP firmware cache refresh failed (exit 1)",
        "cache unavailable",
    )
    status.log.assert_any_call("ESP firmware refresh failed; continuing with existing cache")
    deployment.deploy.assert_awaited_once_with(staged_release)
