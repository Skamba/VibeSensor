from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker
from vibesensor.use_cases.updates.transport_lifecycle import UpdateTransportLifecycle


def _make_tracker(status: UpdateJobStatus | None = None) -> UpdateStatusTracker:
    store = UpdateStateStore()
    return UpdateStatusTracker(
        state_store=store,
        status=status if status is not None else UpdateJobStatus(),
    )


def _running_status(
    phase: UpdatePhase,
    *,
    finished_at: float | None = None,
    transport: UpdateTransport = UpdateTransport.wifi,
) -> UpdateJobStatus:
    return UpdateJobStatus(
        state=UpdateState.running,
        phase=phase,
        transport=transport,
        started_at=time.time() - 60,
        finished_at=finished_at,
    )


def _transport_sessions(session: object) -> SimpleNamespace:
    return SimpleNamespace(
        for_request=lambda request: session,
        for_transport=lambda transport: session,
    )


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


class TestNeedsRecovery:
    def test_running_without_finished_at_needs_recovery(self) -> None:
        tracker = _make_tracker(_running_status(UpdatePhase.installing))
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(None),
        )
        assert lifecycle.needs_recovery() is True

    def test_idle_does_not_need_recovery(self) -> None:
        tracker = _make_tracker(UpdateJobStatus())
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(None),
        )
        assert lifecycle.needs_recovery() is False

    def test_running_with_finished_at_does_not_need_recovery(self) -> None:
        tracker = _make_tracker(
            _running_status(
                UpdatePhase.done,
                finished_at=time.time() - 30,
            ),
        )
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(None),
        )
        assert lifecycle.needs_recovery() is False


class TestPrepare:
    @pytest.mark.asyncio
    async def test_prepare_delegates_to_transport_session(self) -> None:
        tracker = _make_tracker(_running_status(UpdatePhase.validating))
        session = AsyncMock()
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(session),
        )
        request = _wifi_request()

        await lifecycle.prepare(request)

        session.prepare.assert_awaited_once_with(request)
        session.abort_preparation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prepare_aborts_partial_transport_setup_on_failure(self) -> None:
        tracker = _make_tracker(_running_status(UpdatePhase.connecting_wifi))
        session = AsyncMock()
        session.prepare.side_effect = UpdateTransportError("transport failed")
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(session),
        )

        with pytest.raises(UpdateTransportError, match="transport failed"):
            await lifecycle.prepare(_wifi_request())

        session.prepare.assert_awaited_once()
        session.abort_preparation.assert_awaited_once()


class TestLifecycleOperations:
    @pytest.mark.asyncio
    async def test_complete_success_uses_current_transport(self) -> None:
        tracker = _make_tracker(_running_status(UpdatePhase.installing))
        session = AsyncMock()
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(session),
        )

        await lifecycle.complete_success(message="done")

        session.complete_success.assert_awaited_once_with("done")

    @pytest.mark.asyncio
    async def test_cleanup_after_update_uses_current_transport(self) -> None:
        tracker = _make_tracker(_running_status(UpdatePhase.installing))
        session = AsyncMock()
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(session),
        )

        await lifecycle.cleanup_after_update()

        session.cleanup_after_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recover_interrupted_update_uses_current_transport(self) -> None:
        tracker = _make_tracker(_running_status(UpdatePhase.connecting_wifi))
        session = AsyncMock()
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(session),
        )

        await lifecycle.recover_interrupted_update()

        session.recover_interrupted_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recovery_state_can_be_persisted_through_manager_flow(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "update_state.json"
        store = UpdateStateStore(path=state_path)
        tracker = UpdateStatusTracker(
            state_store=store,
            status=_running_status(UpdatePhase.installing),
        )
        session = AsyncMock()
        lifecycle = UpdateTransportLifecycle(
            tracker=tracker,
            sessions_factory=lambda: _transport_sessions(session),
        )

        tracker.mark_interrupted("Update interrupted by server restart")
        await lifecycle.recover_interrupted_update()
        tracker.persist()

        reloaded = store.load()
        assert reloaded is not None
        assert reloaded.state == UpdateState.failed
        assert reloaded.finished_at is not None
