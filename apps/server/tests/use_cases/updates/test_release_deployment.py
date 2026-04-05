from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.wheel_installation import WheelInstallResult


def _staged_release(version: str = "2025.6.15") -> SimpleNamespace:
    return SimpleNamespace(
        wheel_path=Path("/tmp/vibesensor.whl"),
        release=SimpleNamespace(version=version, tag=f"server-v{version}"),
    )


def _make_coordinator() -> tuple[
    UpdateReleaseDeploymentCoordinator,
    MagicMock,
    MagicMock,
]:
    installer = MagicMock()
    installer.snapshot_for_rollback = AsyncMock()
    installer.install_release = AsyncMock()
    installer.rollback = AsyncMock()
    status = MagicMock()
    return (
        UpdateReleaseDeploymentCoordinator(
            installer=installer,
            status=status,
        ),
        installer,
        status,
    )


@pytest.mark.asyncio
async def test_deploy_aborts_before_live_mutation_when_snapshot_fails() -> None:
    coordinator, installer, status = _make_coordinator()
    installer.snapshot_for_rollback.return_value = False

    with pytest.raises(
        UpdateReleaseError,
        match="Rollback snapshot could not be created",
    ) as excinfo:
        await coordinator.deploy(_staged_release())

    status.transition.assert_called_once_with(UpdatePhase.installing)
    assert excinfo.value.phase == UpdatePhase.installing.value
    assert excinfo.value.detail == "Install aborted before mutating the live environment"
    status.fail.assert_not_called()
    status.log.assert_called_once_with("Installing update...")
    installer.install_release.assert_not_awaited()
    installer.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_deploy_snapshots_before_install(tmp_path: Path) -> None:
    coordinator, installer, _status = _make_coordinator()
    events: list[str] = []
    staged_release = SimpleNamespace(
        wheel_path=tmp_path / "vibesensor.whl",
        release=SimpleNamespace(version="2025.6.15", tag="server-v2025.6.15"),
    )

    async def snapshot_for_rollback() -> bool:
        events.append("snapshot")
        return True

    async def install_release(wheel_path: Path, expected_version: str) -> WheelInstallResult:
        events.append(f"install:{wheel_path.name}:{expected_version}")
        return WheelInstallResult(succeeded=True, rollback_required=False)

    installer.snapshot_for_rollback.side_effect = snapshot_for_rollback
    installer.install_release.side_effect = install_release

    await coordinator.deploy(staged_release)

    assert events == [
        "snapshot",
        "install:vibesensor.whl:2025.6.15",
    ]


@pytest.mark.asyncio
async def test_deploy_raises_plain_failure_without_rollback_for_non_mutating_rejection() -> None:
    coordinator, installer, status = _make_coordinator()
    installer.snapshot_for_rollback.return_value = True
    installer.install_release.return_value = WheelInstallResult(
        succeeded=False,
        rollback_required=False,
    )

    with pytest.raises(UpdateReleaseError, match="Update install failed"):
        await coordinator.deploy(_staged_release())

    installer.rollback.assert_not_awaited()
    status.fail.assert_not_called()
    status.log.assert_any_call("Installing update...")


@pytest.mark.asyncio
async def test_deploy_attempts_rollback_after_mutating_failure() -> None:
    coordinator, installer, status = _make_coordinator()
    installer.snapshot_for_rollback.return_value = True
    installer.install_release.return_value = WheelInstallResult(
        succeeded=False,
        rollback_required=True,
    )
    installer.rollback.return_value = True

    with pytest.raises(
        UpdateReleaseError,
        match="Update install failed; rollback restored the previous version",
    ):
        await coordinator.deploy(_staged_release())

    installer.rollback.assert_awaited_once_with()
    status.log.assert_any_call("Attempting rollback...")
