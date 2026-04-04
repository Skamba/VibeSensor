from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler


@pytest.mark.asyncio
async def test_schedule_uses_systemd_run_when_available(tmp_path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    commands = MagicMock()
    commands.run = AsyncMock(return_value=(0, "", ""))
    scheduler = UpdateRestartScheduler(
        commands=commands,
        status=status,
        service_name="vibesensor.service",
        restart_unit="vibesensor-post-update-restart",
    )

    assert await scheduler.schedule() is True
    commands.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_falls_back_to_direct_systemctl_restart(tmp_path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    commands = MagicMock()
    commands.run = AsyncMock(side_effect=[(1, "", "boom"), (0, "", "")])
    scheduler = UpdateRestartScheduler(
        commands=commands,
        status=status,
        service_name="vibesensor.service",
        restart_unit="vibesensor-post-update-restart",
    )

    assert await scheduler.schedule() is True
    assert commands.run.await_count == 2
