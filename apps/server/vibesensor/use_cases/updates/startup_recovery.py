"""Startup recovery coordination for interrupted updater runs."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateState,
    UpdateTerminalState,
)
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.rollback_verification import RollbackDeploymentVerifier
from vibesensor.use_cases.updates.status import (
    UpdateStatusTracker,
    UpdateTerminalStateReporter,
)
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator

__all__ = ["UpdateStartupRecoveryCoordinator"]

_CLEANUP_FAILED_TERMINAL_STATES = frozenset(
    {
        UpdateTerminalState.cleanup_failed,
        UpdateTerminalState.cancelled_cleanup_failed,
        UpdateTerminalState.timeout_cleanup_failed,
    }
)


class UpdateStartupRecoveryCoordinator:
    """Recover transport-owned updater state after an interrupted server restart."""

    __slots__ = (
        "_reporter",
        "_rollback_snapshots",
        "_rollback_verifier",
        "_status",
        "_transport_coordinator",
    )

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        reporter: UpdateTerminalStateReporter,
        transport_coordinator: UpdateTransportCoordinator,
        rollback_snapshots: RollbackSnapshotStore | None = None,
        rollback_verifier: RollbackDeploymentVerifier | None = None,
    ) -> None:
        self._reporter = reporter
        self._status = status
        self._transport_coordinator = transport_coordinator
        self._rollback_snapshots = rollback_snapshots
        self._rollback_verifier = rollback_verifier

    async def recover(self) -> None:
        status = self._status.status
        if status.terminal_state in _CLEANUP_FAILED_TERMINAL_STATES:
            await self._transport_coordinator.recover_interrupted(status)
            await self._verify_rollback_after_interruption(status)
            return
        if status.state != UpdateState.running or status.finished_at is not None:
            return
        self._reporter.mark_interrupted("Update interrupted by server restart")
        await self._transport_coordinator.recover_interrupted(status)
        await self._verify_rollback_after_interruption(status)

    async def _verify_rollback_after_interruption(self, status: UpdateJobStatus) -> None:
        if (
            self._rollback_snapshots is None
            or self._rollback_verifier is None
            or status.phase is not UpdatePhase.installing
        ):
            return
        snapshot = self._rollback_snapshots.load_snapshot(report_issues=False)
        if snapshot is None:
            return
        await self._rollback_verifier.verify(snapshot.metadata)
