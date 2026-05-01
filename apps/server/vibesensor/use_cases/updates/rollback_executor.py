"""Canonical rollback execution from one metadata-pinned snapshot."""

from __future__ import annotations

from vibesensor.use_cases.updates.artifact_validation import WheelArtifactValidator
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.rollback_verification import RollbackDeploymentVerifier
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wheel_installation import WheelInstallExecutor


class RollbackExecutor:
    """Reinstall the one canonical rollback snapshot after update failure."""

    __slots__ = (
        "_rollback_snapshots",
        "_status",
        "_wheel_install_executor",
        "_wheel_validator",
        "_rollback_verifier",
    )

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        rollback_snapshots: RollbackSnapshotStore,
        wheel_validator: WheelArtifactValidator,
        wheel_install_executor: WheelInstallExecutor,
        rollback_verifier: RollbackDeploymentVerifier,
    ) -> None:
        self._status = status
        self._rollback_snapshots = rollback_snapshots
        self._wheel_validator = wheel_validator
        self._wheel_install_executor = wheel_install_executor
        self._rollback_verifier = rollback_verifier

    async def rollback(self) -> bool:
        self._status.log("Rolling back to previous version...")
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
        installed = await self._wheel_install_executor.install_rollback_wheel(
            snapshot.wheel_path,
            expected_version=snapshot.metadata.version,
        )
        if not installed:
            return False
        return await self._rollback_verifier.verify(snapshot.metadata)
