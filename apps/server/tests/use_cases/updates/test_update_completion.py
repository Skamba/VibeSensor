from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateState,
    UpdateTerminalState,
)
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateTerminalStateReporter,
    build_update_status_tracker,
)


class RecordingPreparedTransport:
    def __init__(self) -> None:
        self.completed = False

    async def complete_success(self) -> None:
        self.completed = True


class RecordingRestartScheduler:
    def __init__(self, *, result: bool) -> None:
        self.result = result
        self.scheduled = False

    async def schedule(self) -> bool:
        self.scheduled = True
        return self.result


@pytest.mark.asyncio
async def test_completion_finishes_transport_then_schedules_restart(tmp_path: Path) -> None:
    status = build_update_status_tracker(
        state_store=UpdateStateStore(tmp_path / "update_status.json"),
        status=UpdateJobStatus(state=UpdateState.running, phase=UpdatePhase.installing),
    )
    restart_scheduler = RecordingRestartScheduler(result=True)
    prepared_transport = RecordingPreparedTransport()
    coordinator = UpdateCompletionCoordinator(
        restart_scheduler=restart_scheduler,
        reporter=UpdateTerminalStateReporter(status=status),
        status=status,
    )

    await coordinator.complete_success(
        prepared_transport,
        message="Update completed successfully",
    )

    assert prepared_transport.completed is True
    assert restart_scheduler.scheduled is True
    assert status.status.state is UpdateState.success
    assert status.status.terminal_state is UpdateTerminalState.success
    assert status.status.log_tail == ["Update completed successfully"]
    assert status.status.issues == []


@pytest.mark.asyncio
async def test_completion_records_issue_when_restart_scheduling_fails(tmp_path: Path) -> None:
    status = build_update_status_tracker(
        state_store=UpdateStateStore(tmp_path / "update_status.json"),
        status=UpdateJobStatus(state=UpdateState.running, phase=UpdatePhase.checking),
    )
    restart_scheduler = RecordingRestartScheduler(result=False)
    prepared_transport = RecordingPreparedTransport()
    coordinator = UpdateCompletionCoordinator(
        restart_scheduler=restart_scheduler,
        reporter=UpdateTerminalStateReporter(status=status),
        status=status,
    )

    await coordinator.complete_success(
        prepared_transport,
        message="No server update needed; ESP firmware checked",
    )

    assert prepared_transport.completed is True
    assert restart_scheduler.scheduled is True
    assert status.status.state is UpdateState.success
    assert status.status.log_tail == [
        "No server update needed; ESP firmware checked",
        "Automatic backend restart scheduling failed",
    ]
    assert [(issue.phase, issue.message, issue.detail) for issue in status.status.issues] == [
        (
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        ),
    ]
