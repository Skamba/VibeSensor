"""Public installer facade over focused updater artifact collaborators."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.artifact_validation import WheelArtifactValidator
from vibesensor.use_cases.updates.rollback_executor import RollbackExecutor
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.rollback_snapshot_builder import RollbackSnapshotBuilder
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wheel_installation import WheelInstallExecutor


@dataclass(frozen=True, slots=True)
class UpdateInstallerConfig:
    repo: Path
    rollback_dir: Path
    reinstall_timeout_s: float


class UpdateInstaller:
    """Own install policy while delegating execution to focused collaborators."""

    __slots__ = (
        "_config",
        "_rollback_executor",
        "_rollback_snapshot_builder",
        "_tracker",
        "_wheel_install_executor",
    )

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateInstallerConfig,
    ) -> None:
        self._config = config
        self._tracker = tracker
        rollback_snapshots = RollbackSnapshotStore(config.rollback_dir, tracker)
        wheel_validator = WheelArtifactValidator(tracker)
        self._wheel_install_executor = WheelInstallExecutor(
            commands=commands,
            tracker=tracker,
            repo=config.repo,
            reinstall_timeout_s=config.reinstall_timeout_s,
            wheel_validator=wheel_validator,
        )
        self._rollback_snapshot_builder = RollbackSnapshotBuilder(
            commands=commands,
            tracker=tracker,
            repo=config.repo,
            rollback_dir=config.rollback_dir,
            rollback_snapshots=rollback_snapshots,
        )
        self._rollback_executor = RollbackExecutor(
            tracker=tracker,
            rollback_dir=config.rollback_dir,
            rollback_snapshots=rollback_snapshots,
            wheel_validator=wheel_validator,
            wheel_install_executor=self._wheel_install_executor,
        )

    async def snapshot_for_rollback(self) -> bool:
        return await self._rollback_snapshot_builder.snapshot_for_rollback()

    async def install_release(self, wheel_path: Path, expected_version: str) -> None:
        install_result = await self._wheel_install_executor.install_release(
            wheel_path,
            expected_version,
        )
        if install_result.succeeded:
            return
        rollback_succeeded = False
        if install_result.rollback_required:
            self._tracker.log("Attempting rollback...")
            rollback_succeeded = await self.rollback()
        if rollback_succeeded:
            raise UpdateReleaseError(
                "Update install failed; rollback restored the previous version"
            )
        if install_result.rollback_required:
            raise UpdateReleaseError("Update install failed and rollback did not complete")
        raise UpdateReleaseError("Update install failed")

    async def rollback(self) -> bool:
        return await self._rollback_executor.rollback()
