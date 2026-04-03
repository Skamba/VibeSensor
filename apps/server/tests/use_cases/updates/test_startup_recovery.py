from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.use_cases.updates.models import UpdateJobStatus, UpdateState, UpdateTransport
from vibesensor.use_cases.updates.startup_recovery import UpdateStartupRecoveryCoordinator


def _make_recovery(
    status: UpdateJobStatus,
) -> tuple[
    UpdateStartupRecoveryCoordinator,
    MagicMock,
    AsyncMock,
    MagicMock,
    MagicMock,
]:
    tracker = MagicMock()
    tracker.status = status
    status_controller = MagicMock()
    status_recorder = MagicMock()
    session = AsyncMock()
    transport_sessions = MagicMock()
    transport_sessions.for_status.return_value = session
    return (
        UpdateStartupRecoveryCoordinator(
            tracker=tracker,
            status_controller=status_controller,
            status_recorder=status_recorder,
            transport_sessions=transport_sessions,
        ),
        transport_sessions,
        session.recover_interrupted_update,
        status_controller,
        status_recorder,
    )


@pytest.mark.asyncio
async def test_recover_skips_non_running_jobs() -> None:
    coordinator, transport_sessions, recover, status_controller, status_recorder = _make_recovery(
        UpdateJobStatus(state=UpdateState.idle),
    )

    await coordinator.recover()

    transport_sessions.for_status.assert_not_called()
    recover.assert_not_awaited()
    status_controller.mark_interrupted.assert_not_called()
    status_recorder.add_issue.assert_not_called()


@pytest.mark.asyncio
async def test_recover_marks_interrupted_and_recovers_transport_session() -> None:
    coordinator, transport_sessions, recover, status_controller, status_recorder = _make_recovery(
        UpdateJobStatus(
            state=UpdateState.running,
            transport=UpdateTransport.usb_internet,
        ),
    )

    await coordinator.recover()

    transport_sessions.for_status.assert_called_once()
    recover.assert_awaited_once_with()
    status_recorder.add_issue.assert_called_once_with(
        "startup",
        "Update interrupted by server restart",
    )
    status_controller.mark_interrupted.assert_called_once_with()
    status_controller.persist.assert_called_once_with()
