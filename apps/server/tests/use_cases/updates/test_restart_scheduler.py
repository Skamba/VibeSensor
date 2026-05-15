from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import CommandExecutionResult


@pytest.mark.asyncio
async def test_schedule_uses_systemd_run_when_available(tmp_path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    commands = MagicMock()
    commands.run = AsyncMock(
        return_value=CommandExecutionResult(returncode=0, stdout="", stderr=""),
    )
    scheduler = UpdateRestartScheduler(
        commands=commands,
        status=status,
        service_name="vibesensor.service",
        restart_unit="vibesensor-post-update-restart",
    )

    assert await scheduler.schedule() is True
    commands.run.assert_awaited_once()
    assert commands.run.await_args.args[0] == [
        "systemd-run",
        "--unit",
        "vibesensor-post-update-restart",
        "--on-active=2s",
        "systemctl",
        "restart",
        "vibesensor.service",
    ]


@pytest.mark.asyncio
async def test_schedule_falls_back_to_direct_systemctl_restart(tmp_path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    commands = MagicMock()
    commands.run = AsyncMock(
        side_effect=[
            CommandExecutionResult(returncode=1, stdout="", stderr="boom"),
            CommandExecutionResult(returncode=0, stdout="", stderr=""),
        ],
    )
    scheduler = UpdateRestartScheduler(
        commands=commands,
        status=status,
        service_name="vibesensor.service",
        restart_unit="vibesensor-post-update-restart",
    )

    assert await scheduler.schedule() is True
    assert commands.run.await_count == 2
    assert [call.args[0] for call in commands.run.await_args_list] == [
        [
            "systemd-run",
            "--unit",
            "vibesensor-post-update-restart",
            "--on-active=2s",
            "systemctl",
            "restart",
            "vibesensor.service",
        ],
        ["systemctl", "restart", "vibesensor.service"],
    ]
