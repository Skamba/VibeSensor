from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.use_cases.updates.firmware import FirmwareRefreshResult
from vibesensor.use_cases.updates.models import (
    UpdateExecutionOutcome,
    UpdatePhase,
    UpdateRequest,
    UpdateTransport,
)
from vibesensor.use_cases.updates.run_models import (
    InstallServerReleasePlan,
    PlannedUpdateRun,
    PreparedUpdateRun,
)
from vibesensor.use_cases.updates.server_release_execution import (
    ServerReleaseExecutionCoordinator,
)


def _build_status_tracker(state_path: Path):
    tracker = build_update_status_harness(state_path)
    tracker.start_job(
        UpdateRequest(
            transport=UpdateTransport.wifi,
            ssid="TestNet",
            password="secret-passphrase",
        ),
    )
    tracker.transition(UpdatePhase.stopping_hotspot)
    tracker.transition(UpdatePhase.connecting_wifi)
    tracker.transition(UpdatePhase.checking)
    tracker.transition(UpdatePhase.downloading)
    return tracker


class _StaticStager:
    def __init__(self, staged_release: object) -> None:
        self._staged_release = staged_release

    @asynccontextmanager
    async def stage(self, release: object):
        assert release is self._staged_release.release
        yield self._staged_release


class _StaticFirmwareRefresher:
    def __init__(self, result: FirmwareRefreshResult) -> None:
        self._result = result
        self.pinned_tags: list[str] = []

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> FirmwareRefreshResult:
        self.pinned_tags.append(pinned_tag)
        return self._result


class _RecordingDeployment:
    def __init__(self) -> None:
        self.deployed_release: object | None = None

    async def deploy(self, staged_release: object) -> None:
        self.deployed_release = staged_release


def _workflow(release: object, prepared_transport: object) -> tuple[PlannedUpdateRun, object]:
    plan = InstallServerReleasePlan(release=release)
    return (
        PlannedUpdateRun(
            prepared=PreparedUpdateRun(prepared_transport=prepared_transport),
            execution_plan=plan,
        ),
        plan,
    )


@pytest.mark.asyncio
async def test_execute_deploys_staged_release_after_successful_refresh(tmp_path: Path) -> None:
    status = _build_status_tracker(tmp_path / "update-state.json")
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    firmware_refresher = _StaticFirmwareRefresher(FirmwareRefreshResult.success())
    deployment = _RecordingDeployment()
    completion = MagicMock()
    completion.complete_success = AsyncMock()
    coordinator = ServerReleaseExecutionCoordinator(
        completion=completion,
        stager=_StaticStager(staged_release),
        firmware_refresher=firmware_refresher,
        deployment=deployment,
        status=status,
    )
    prepared_transport = object()
    workflow, plan = _workflow(release, prepared_transport)

    result = await coordinator.execute(workflow, plan)

    assert result == UpdateExecutionOutcome.installed
    assert firmware_refresher.pinned_tags == ["server-v2026.4.4"]
    assert deployment.deployed_release is staged_release
    assert status.status.issues == []
    completion.complete_success.assert_awaited_once_with(
        prepared_transport,
        message="Update completed successfully",
    )


@pytest.mark.asyncio
async def test_execute_records_firmware_refresh_failure_and_still_deploys(tmp_path: Path) -> None:
    status = _build_status_tracker(tmp_path / "update-state.json")
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    firmware_refresher = _StaticFirmwareRefresher(
        FirmwareRefreshResult.failure(
            message="ESP firmware cache refresh failed (exit 4)",
            detail="download timed out",
        ),
    )
    deployment = _RecordingDeployment()
    completion = MagicMock()
    completion.complete_success = AsyncMock()
    coordinator = ServerReleaseExecutionCoordinator(
        completion=completion,
        stager=_StaticStager(staged_release),
        firmware_refresher=firmware_refresher,
        deployment=deployment,
        status=status,
    )
    workflow, plan = _workflow(release, object())

    await coordinator.execute(workflow, plan)

    assert deployment.deployed_release is staged_release
    assert firmware_refresher.pinned_tags == ["server-v2026.4.4"]
    assert status.status.issues[-1].message == "ESP firmware cache refresh failed (exit 4)"
    assert status.status.issues[-1].detail == "download timed out"
    assert "ESP firmware refresh failed; continuing with existing cache" in status.status.log_tail
    completion.complete_success.assert_awaited_once()
