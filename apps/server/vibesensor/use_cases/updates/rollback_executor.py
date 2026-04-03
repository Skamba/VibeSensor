"""Canonical rollback execution from one metadata-pinned snapshot."""

from __future__ import annotations

from vibesensor.use_cases.updates.artifact_validation import WheelArtifactValidator
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wheel_installation import WheelInstallExecutor


class RollbackExecutor:
    """Reinstall the one canonical rollback snapshot after update failure."""

    __slots__ = (
        "_rollback_snapshots",
        "_tracker",
        "_wheel_install_executor",
        "_wheel_validator",
    )

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        rollback_snapshots: RollbackSnapshotStore,
        wheel_validator: WheelArtifactValidator,
        wheel_install_executor: WheelInstallExecutor,
    ) -> None:
        self._tracker = tracker
        self._rollback_snapshots = rollback_snapshots
        self._wheel_validator = wheel_validator
        self._wheel_install_executor = wheel_install_executor

    async def rollback(self) -> bool:
        self._tracker.log("Rolling back to previous version...")
        snapshot = self._rollback_snapshots.load_snapshot()
        if snapshot is None:
            return False
        if not self._wheel_validator.validate_wheel(
            snapshot.wheel_path,
            phase="installing",
            context="Rollback snapshot wheel",
            fatal=False,
            expected_sha256=snapshot.metadata.sha256,
        ):
            return False
        return await self._wheel_install_executor.install_rollback_wheel(
            snapshot.wheel_path,
            expected_version=snapshot.metadata.version,
        )
