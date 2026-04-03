from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.release_installation import (
    UpdateReleaseInstallationCoordinator,
)
from vibesensor.use_cases.updates.wheel_installation import WheelInstallResult


def _staged_release(version: str = "2025.6.15") -> SimpleNamespace:
    return SimpleNamespace(
        wheel_path=Path("/tmp/vibesensor.whl"),
        release=SimpleNamespace(version=version),
    )


def _make_coordinator() -> tuple[
    UpdateReleaseInstallationCoordinator,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    installer = MagicMock()
    installer.snapshot_for_rollback = AsyncMock()
    installer.install_release = AsyncMock()
    installer.rollback = AsyncMock()
    status_controller = MagicMock()
    status_recorder = MagicMock()
    return (
        UpdateReleaseInstallationCoordinator(
            installer=installer,
            status_controller=status_controller,
            status_recorder=status_recorder,
        ),
        installer,
        status_controller,
        status_recorder,
    )


@pytest.mark.asyncio
async def test_install_aborts_before_live_mutation_when_snapshot_fails() -> None:
    coordinator, installer, status_controller, status_recorder = _make_coordinator()
    installer.snapshot_for_rollback.return_value = False

    with pytest.raises(UpdateReleaseError, match="Rollback snapshot could not be created"):
        await coordinator.install(_staged_release())

    status_controller.transition.assert_called_once_with(UpdatePhase.installing)
    status_controller.mark_failed.assert_called_once_with()
    installer.install_release.assert_not_awaited()
    installer.rollback.assert_not_awaited()
    status_recorder.add_issue.assert_called_once()


@pytest.mark.asyncio
async def test_install_raises_plain_failure_without_rollback_for_non_mutating_rejection() -> None:
    coordinator, installer, status_controller, status_recorder = _make_coordinator()
    installer.snapshot_for_rollback.return_value = True
    installer.install_release.return_value = WheelInstallResult(
        succeeded=False,
        rollback_required=False,
    )

    with pytest.raises(UpdateReleaseError, match="Update install failed"):
        await coordinator.install(_staged_release())

    installer.rollback.assert_not_awaited()
    status_controller.mark_failed.assert_not_called()
    status_recorder.log.assert_called_once_with("Installing update...")


@pytest.mark.asyncio
async def test_install_attempts_rollback_after_mutating_failure() -> None:
    coordinator, installer, _status_controller, status_recorder = _make_coordinator()
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
        await coordinator.install(_staged_release())

    installer.rollback.assert_awaited_once_with()
    status_recorder.log.assert_any_call("Attempting rollback...")
