from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator


@pytest.mark.asyncio
async def test_completion_finishes_transport_then_schedules_restart() -> None:
    restart_scheduler = MagicMock()
    restart_scheduler.schedule = AsyncMock(return_value=True)
    reporter = MagicMock()
    status = MagicMock()
    prepared_transport = MagicMock()
    prepared_transport.complete_success = AsyncMock()
    coordinator = UpdateCompletionCoordinator(
        restart_scheduler=restart_scheduler,
        reporter=reporter,
        status=status,
    )

    await coordinator.complete_success(
        prepared_transport,
        message="Update completed successfully",
    )

    prepared_transport.complete_success.assert_awaited_once_with()
    reporter.mark_success.assert_called_once_with("Update completed successfully")
    restart_scheduler.schedule.assert_awaited_once_with()
    status.add_issue.assert_not_called()
    status.log.assert_not_called()


@pytest.mark.asyncio
async def test_completion_records_issue_when_restart_scheduling_fails() -> None:
    restart_scheduler = MagicMock()
    restart_scheduler.schedule = AsyncMock(return_value=False)
    reporter = MagicMock()
    status = MagicMock()
    prepared_transport = MagicMock()
    prepared_transport.complete_success = AsyncMock()
    coordinator = UpdateCompletionCoordinator(
        restart_scheduler=restart_scheduler,
        reporter=reporter,
        status=status,
    )

    await coordinator.complete_success(
        prepared_transport,
        message="No server update needed; ESP firmware checked",
    )

    prepared_transport.complete_success.assert_awaited_once_with()
    reporter.mark_success.assert_called_once_with(
        "No server update needed; ESP firmware checked",
    )
    status.add_issue.assert_called_once_with(
        "done",
        "Backend restart was not scheduled automatically",
        "Run 'sudo systemctl restart vibesensor.service' manually",
    )
    status.log.assert_called_once_with("Automatic backend restart scheduling failed")
