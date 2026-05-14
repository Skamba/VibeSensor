from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateState,
    UpdateTerminalState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.startup_recovery import UpdateStartupRecoveryCoordinator
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateTerminalStateReporter,
    build_update_status_tracker,
)


class RecordingTransportCoordinator:
    def __init__(self) -> None:
        self.recovered_statuses: list[UpdateJobStatus] = []

    async def recover_interrupted(self, status: UpdateJobStatus) -> None:
        self.recovered_statuses.append(status)


@dataclass(frozen=True, slots=True)
class Snapshot:
    metadata: object


class SnapshotStore:
    def __init__(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        self.load_attempts = 0

    def load_snapshot(self, *, report_issues: bool = True) -> Snapshot | None:
        assert report_issues is False
        self.load_attempts += 1
        return self.snapshot


class RollbackVerifier:
    def __init__(self, *, result: bool) -> None:
        self.result = result
        self.verified_metadata: list[object] = []

    async def verify(self, metadata: object) -> bool:
        self.verified_metadata.append(metadata)
        return self.result


def _make_recovery(
    tmp_path: Path,
    status: UpdateJobStatus,
    *,
    rollback_snapshots: SnapshotStore | None = None,
    rollback_verifier: RollbackVerifier | None = None,
) -> tuple[UpdateStartupRecoveryCoordinator, RecordingTransportCoordinator]:
    status_tracker = build_update_status_tracker(
        state_store=UpdateStateStore(tmp_path / "update_status.json"),
        status=status,
    )
    transport_coordinator = RecordingTransportCoordinator()
    coordinator = UpdateStartupRecoveryCoordinator(
        status=status_tracker,
        reporter=UpdateTerminalStateReporter(status=status_tracker),
        transport_coordinator=transport_coordinator,
        rollback_snapshots=rollback_snapshots,
        rollback_verifier=rollback_verifier,
    )
    return coordinator, transport_coordinator


@pytest.mark.asyncio
async def test_recover_skips_non_running_jobs(tmp_path: Path) -> None:
    status = UpdateJobStatus(state=UpdateState.idle)
    coordinator, transport_coordinator = _make_recovery(tmp_path, status)

    await coordinator.recover()

    assert transport_coordinator.recovered_statuses == []
    assert status.state is UpdateState.idle
    assert status.issues == []


@pytest.mark.asyncio
async def test_recover_marks_interrupted_recovers_transport_and_verifies_snapshot(
    tmp_path: Path,
) -> None:
    metadata = object()
    rollback_snapshots = SnapshotStore(Snapshot(metadata=metadata))
    rollback_verifier = RollbackVerifier(result=True)
    status = UpdateJobStatus(
        state=UpdateState.running,
        phase=UpdatePhase.installing,
        transport=UpdateTransport.usb_internet,
    )
    coordinator, transport_coordinator = _make_recovery(
        tmp_path,
        status,
        rollback_snapshots=rollback_snapshots,
        rollback_verifier=rollback_verifier,
    )

    await coordinator.recover()

    assert transport_coordinator.recovered_statuses == [status]
    assert status.state is UpdateState.failed
    assert [(issue.phase, issue.message) for issue in status.issues] == [
        ("startup", "Update interrupted by server restart"),
    ]
    assert rollback_snapshots.load_attempts == 1
    assert rollback_verifier.verified_metadata == [metadata]


@pytest.mark.asyncio
async def test_recover_repairs_cleanup_failed_terminal_state(tmp_path: Path) -> None:
    status = UpdateJobStatus(
        state=UpdateState.failed,
        finished_at=123.0,
        terminal_state=UpdateTerminalState.timeout_cleanup_failed,
    )
    coordinator, transport_coordinator = _make_recovery(tmp_path, status)

    await coordinator.recover()

    assert transport_coordinator.recovered_statuses == [status]
    assert status.state is UpdateState.failed
    assert status.issues == []
