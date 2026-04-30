from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateState,
    UpdateTerminalState,
    UpdateTransport,
)
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
    status_tracker = MagicMock()
    status_tracker.status = status
    reporter = MagicMock()
    transport_coordinator = MagicMock()
    transport_coordinator.recover_interrupted = AsyncMock()
    return (
        UpdateStartupRecoveryCoordinator(
            status=status_tracker,
            reporter=reporter,
            transport_coordinator=transport_coordinator,
        ),
        transport_coordinator,
        transport_coordinator.recover_interrupted,
        reporter,
        status_tracker,
    )


@pytest.mark.asyncio
async def test_recover_skips_non_running_jobs() -> None:
    (
        coordinator,
        transport_coordinator,
        recover,
        reporter,
        status_tracker,
    ) = _make_recovery(UpdateJobStatus(state=UpdateState.idle))

    await coordinator.recover()

    transport_coordinator.recover_interrupted.assert_not_called()
    recover.assert_not_awaited()
    reporter.mark_interrupted.assert_not_called()


@pytest.mark.asyncio
async def test_recover_marks_interrupted_and_recovers_transport() -> None:
    (
        coordinator,
        transport_coordinator,
        recover,
        reporter,
        status_tracker,
    ) = _make_recovery(
        UpdateJobStatus(
            state=UpdateState.running,
            transport=UpdateTransport.usb_internet,
        ),
    )

    await coordinator.recover()

    transport_coordinator.recover_interrupted.assert_awaited_once_with(
        UpdateJobStatus(
            state=UpdateState.running,
            transport=UpdateTransport.usb_internet,
        ),
    )
    reporter.mark_interrupted.assert_called_once_with("Update interrupted by server restart")


@pytest.mark.asyncio
async def test_recover_repairs_cleanup_failed_terminal_state() -> None:
    status = UpdateJobStatus(
        state=UpdateState.failed,
        finished_at=123.0,
        terminal_state=UpdateTerminalState.timeout_cleanup_failed,
    )
    (
        coordinator,
        transport_coordinator,
        recover,
        reporter,
        status_tracker,
    ) = _make_recovery(status)

    await coordinator.recover()

    transport_coordinator.recover_interrupted.assert_awaited_once_with(status)
    reporter.mark_interrupted.assert_not_called()
