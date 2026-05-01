"""Low-level install, rollback, and snapshot primitives for updater workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.artifact_validation import WheelArtifactValidator
from vibesensor.use_cases.updates.rollback_executor import RollbackExecutor
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.rollback_snapshot_builder import RollbackSnapshotBuilder
from vibesensor.use_cases.updates.rollback_verification import (
    RollbackDeploymentVerifier,
    RollbackVerificationConfig,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wheel_installation import WheelInstallExecutor, WheelInstallResult


@dataclass(frozen=True, slots=True)
class UpdateInstallerConfig:
    repo: Path
    rollback_dir: Path
    reinstall_timeout_s: float
    smoke_config_path: Path | None = None


class UpdateInstaller:
    """Expose install-time primitives without embedding rollback policy decisions."""

    __slots__ = (
        "_config",
        "_rollback_executor",
        "_rollback_snapshot_builder",
        "_wheel_install_executor",
    )

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        config: UpdateInstallerConfig,
    ) -> None:
        self._config = config
        rollback_snapshots = RollbackSnapshotStore(config.rollback_dir, status)
        wheel_validator = WheelArtifactValidator(
            status=status,
        )
        self._wheel_install_executor = WheelInstallExecutor(
            commands=commands,
            status=status,
            repo=config.repo,
            reinstall_timeout_s=config.reinstall_timeout_s,
            wheel_validator=wheel_validator,
        )
        self._rollback_snapshot_builder = RollbackSnapshotBuilder(
            commands=commands,
            status=status,
            repo=config.repo,
            rollback_dir=config.rollback_dir,
            rollback_snapshots=rollback_snapshots,
            config_path=config.smoke_config_path,
        )
        rollback_verifier = RollbackDeploymentVerifier(
            status=status,
            config=RollbackVerificationConfig(
                repo=config.repo,
                source_config=config.smoke_config_path,
            ),
        )
        self._rollback_executor = RollbackExecutor(
            status=status,
            rollback_snapshots=rollback_snapshots,
            wheel_validator=wheel_validator,
            wheel_install_executor=self._wheel_install_executor,
            rollback_verifier=rollback_verifier,
        )

    async def snapshot_for_rollback(self) -> bool:
        return await self._rollback_snapshot_builder.snapshot_for_rollback()

    async def install_release(
        self,
        wheel_path: Path,
        expected_version: str,
    ) -> WheelInstallResult:
        return await self._wheel_install_executor.install_release(
            wheel_path,
            expected_version,
        )

    async def rollback(self) -> bool:
        return await self._rollback_executor.rollback()
