from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.use_cases.updates.models import UpdatePhase, UpdateRequest, UpdateTransport
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
    UpdateReleaseError,
)
from vibesensor.use_cases.updates.wheel_installation import WheelInstallResult


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


class _FakeInstaller:
    def __init__(
        self,
        *,
        snapshot_ok: bool = True,
        install_result: WheelInstallResult | None = None,
        rollback_result: bool = False,
    ) -> None:
        self.snapshot_ok = snapshot_ok
        self.install_result = install_result or WheelInstallResult(
            succeeded=True,
            rollback_required=False,
        )
        self.rollback_result = rollback_result
        self.snapshot_attempted = False
        self.install_args: tuple[Path, str] | None = None
        self.rollback_attempted = False

    async def snapshot_for_rollback(self) -> bool:
        self.snapshot_attempted = True
        return self.snapshot_ok

    async def install_release(self, wheel_path: Path, expected_version: str) -> WheelInstallResult:
        assert self.snapshot_attempted
        self.install_args = (wheel_path, expected_version)
        return self.install_result

    async def rollback(self) -> bool:
        self.rollback_attempted = True
        return self.rollback_result


def _staged_release(version: str, wheel_path: Path) -> object:
    return SimpleNamespace(
        release=SimpleNamespace(version=version),
        wheel_path=wheel_path,
    )


@pytest.mark.asyncio
async def test_deploy_aborts_before_live_mutation_when_snapshot_fails(tmp_path: Path) -> None:
    installer = _FakeInstaller(snapshot_ok=False)
    status = _build_status_tracker(tmp_path / "update-state.json")
    coordinator = UpdateReleaseDeploymentCoordinator(installer=installer, status=status)

    with pytest.raises(
        UpdateReleaseError, match="Rollback snapshot could not be created"
    ) as excinfo:
        await coordinator.deploy(_staged_release("2025.6.15", tmp_path / "release.whl"))

    assert excinfo.value.phase == UpdatePhase.installing.value
    assert excinfo.value.detail == "Install aborted before mutating the live environment"
    assert status.status.phase == UpdatePhase.installing
    assert any("Installing update..." in line for line in status.status.log_tail)
    assert not any("Attempting rollback..." in line for line in status.status.log_tail)
    assert installer.install_args is None


@pytest.mark.asyncio
async def test_deploy_installs_staged_release_after_snapshot(tmp_path: Path) -> None:
    installer = _FakeInstaller()
    status = _build_status_tracker(tmp_path / "update-state.json")
    coordinator = UpdateReleaseDeploymentCoordinator(installer=installer, status=status)
    staged_release = _staged_release("2025.6.15", tmp_path / "release.whl")

    await coordinator.deploy(staged_release)

    assert installer.install_args == (staged_release.wheel_path, "2025.6.15")
    assert installer.rollback_attempted is False
    assert status.status.phase == UpdatePhase.installing
    assert status.status.issues == []


@pytest.mark.asyncio
async def test_deploy_raises_plain_failure_without_rollback_for_non_mutating_rejection(
    tmp_path: Path,
) -> None:
    installer = _FakeInstaller(
        install_result=WheelInstallResult(
            succeeded=False,
            rollback_required=False,
        ),
    )
    status = _build_status_tracker(tmp_path / "update-state.json")
    coordinator = UpdateReleaseDeploymentCoordinator(installer=installer, status=status)

    with pytest.raises(UpdateReleaseError, match="Update install failed"):
        await coordinator.deploy(_staged_release("2025.6.15", tmp_path / "release.whl"))

    assert not any("Attempting rollback..." in line for line in status.status.log_tail)
    assert installer.rollback_attempted is False


@pytest.mark.asyncio
async def test_deploy_logs_rollback_attempt_after_mutating_failure(tmp_path: Path) -> None:
    installer = _FakeInstaller(
        install_result=WheelInstallResult(
            succeeded=False,
            rollback_required=True,
        ),
        rollback_result=True,
    )
    status = _build_status_tracker(tmp_path / "update-state.json")
    coordinator = UpdateReleaseDeploymentCoordinator(installer=installer, status=status)

    with pytest.raises(
        UpdateReleaseError,
        match="Update install failed; rollback restored the previous version",
    ):
        await coordinator.deploy(_staged_release("2025.6.15", tmp_path / "release.whl"))

    assert installer.rollback_attempted is True
    assert any("Attempting rollback..." in line for line in status.status.log_tail)
