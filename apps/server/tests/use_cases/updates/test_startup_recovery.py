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
]:
    status_tracker = MagicMock()
    status_tracker.status = status
    transport_coordinator = MagicMock()
    transport_coordinator.recover_interrupted = AsyncMock()
    return (
        UpdateStartupRecoveryCoordinator(
            status=status_tracker,
            transport_coordinator=transport_coordinator,
        ),
        transport_coordinator,
        transport_coordinator.recover_interrupted,
        status_tracker,
    )


@pytest.mark.asyncio
async def test_recover_skips_non_running_jobs() -> None:
    (
        coordinator,
        transport_coordinator,
        recover,
        status_tracker,
    ) = _make_recovery(UpdateJobStatus(state=UpdateState.idle))

    await coordinator.recover()

    transport_coordinator.recover_interrupted.assert_not_called()
    recover.assert_not_awaited()
    status_tracker.mark_interrupted.assert_not_called()


@pytest.mark.asyncio
async def test_recover_marks_interrupted_and_recovers_transport() -> None:
    (
        coordinator,
        transport_coordinator,
        recover,
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
    status_tracker.mark_interrupted.assert_called_once_with("Update interrupted by server restart")
