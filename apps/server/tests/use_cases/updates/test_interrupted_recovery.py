"""Tests for the InterruptedUpdateRecovery collaborator."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from vibesensor.use_cases.updates.models import UpdateJobStatus, UpdatePhase, UpdateState
from vibesensor.use_cases.updates.recovery import InterruptedUpdateRecovery
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker


def _make_tracker(status: UpdateJobStatus | None = None) -> UpdateStatusTracker:
    store = UpdateStateStore()
    return UpdateStatusTracker(
        state_store=store,
        status=status if status is not None else UpdateJobStatus(),
    )


class TestNeedsRecovery:
    def test_running_without_finished_at_needs_recovery(self) -> None:
        tracker = _make_tracker(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.installing,
                started_at=time.time() - 60,
            ),
        )
        recovery = InterruptedUpdateRecovery(tracker=tracker, wifi_factory=lambda: None)
        assert recovery.needs_recovery() is True

    def test_idle_does_not_need_recovery(self) -> None:
        tracker = _make_tracker(UpdateJobStatus())
        recovery = InterruptedUpdateRecovery(tracker=tracker, wifi_factory=lambda: None)
        assert recovery.needs_recovery() is False

    def test_running_with_finished_at_does_not_need_recovery(self) -> None:
        tracker = _make_tracker(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.done,
                started_at=time.time() - 60,
                finished_at=time.time() - 30,
            ),
        )
        recovery = InterruptedUpdateRecovery(tracker=tracker, wifi_factory=lambda: None)
        assert recovery.needs_recovery() is False

    def test_failed_does_not_need_recovery(self) -> None:
        tracker = _make_tracker(
            UpdateJobStatus(state=UpdateState.failed, finished_at=time.time()),
        )
        recovery = InterruptedUpdateRecovery(tracker=tracker, wifi_factory=lambda: None)
        assert recovery.needs_recovery() is False

    def test_success_does_not_need_recovery(self) -> None:
        tracker = _make_tracker(
            UpdateJobStatus(state=UpdateState.success, finished_at=time.time()),
        )
        recovery = InterruptedUpdateRecovery(tracker=tracker, wifi_factory=lambda: None)
        assert recovery.needs_recovery() is False


class TestRecover:
    @pytest.mark.asyncio
    async def test_marks_as_failed_and_persists(self) -> None:
        tracker = _make_tracker(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.downloading,
                started_at=time.time() - 60,
            ),
        )
        wifi = AsyncMock()
        recovery = InterruptedUpdateRecovery(
            tracker=tracker,
            wifi_factory=lambda: wifi,
        )

        await recovery.recover()

        assert tracker.status.state == UpdateState.failed
        assert tracker.status.finished_at is not None
        issue_messages = [i.message for i in tracker.status.issues]
        assert any("interrupted" in m.lower() or "restart" in m.lower() for m in issue_messages)
        wifi.recover_interrupted_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_calls_wifi_cleanup(self) -> None:
        tracker = _make_tracker(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.connecting_wifi,
                started_at=time.time() - 60,
            ),
        )
        wifi = AsyncMock()
        recovery = InterruptedUpdateRecovery(
            tracker=tracker,
            wifi_factory=lambda: wifi,
        )

        await recovery.recover()

        wifi.recover_interrupted_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persists_state_after_recovery(self, tmp_path) -> None:
        state_path = tmp_path / "update_state.json"
        store = UpdateStateStore(path=state_path)
        store.save(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.installing,
                started_at=time.time() - 60,
            ),
        )
        tracker = UpdateStatusTracker(
            state_store=store,
            status=store.load(),
        )
        wifi = AsyncMock()
        recovery = InterruptedUpdateRecovery(
            tracker=tracker,
            wifi_factory=lambda: wifi,
        )

        await recovery.recover()

        reloaded = store.load()
        assert reloaded is not None
        assert reloaded.state == UpdateState.failed
        assert reloaded.finished_at is not None
