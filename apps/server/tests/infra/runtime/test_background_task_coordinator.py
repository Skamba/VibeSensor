from __future__ import annotations

import asyncio
import contextlib
import logging

import pytest

from vibesensor.infra.runtime.background_task_coordinator import BackgroundTaskCoordinator
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.task_supervisor import TaskSupervisor


async def _stubborn_task() -> None:
    first_wait = asyncio.Event()
    second_wait = asyncio.Event()
    try:
        await first_wait.wait()
    except asyncio.CancelledError:
        await second_wait.wait()


@pytest.mark.asyncio
async def test_start_monitors_failure_via_task_supervisor() -> None:
    health_state = RuntimeHealthState()
    supervisor = TaskSupervisor(
        health_state=health_state,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )
    coordinator = BackgroundTaskCoordinator(
        monitor_task=supervisor.monitor_task,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )

    async def _fail() -> None:
        raise RuntimeError("boom")

    task = coordinator.start(_fail(), name="update-startup-recover")
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    assert health_state.background_task_failures["update-startup-recover"] == "boom"
    assert coordinator.tasks == [task]


@pytest.mark.asyncio
async def test_cancel_all_retains_pending_tasks_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import vibesensor.infra.runtime.background_task_coordinator as coordinator_module

    coordinator = BackgroundTaskCoordinator(
        monitor_task=lambda task: None,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )
    stubborn = asyncio.create_task(_stubborn_task(), name="stubborn-background")
    coordinator.tasks = [stubborn]
    await asyncio.sleep(0)

    async def _wait_pending(tasks, timeout):
        del timeout
        await asyncio.sleep(0)
        return set(), set(tasks)

    monkeypatch.setattr(coordinator_module.asyncio, "wait", _wait_pending)

    with caplog.at_level(logging.WARNING):
        lingering = await coordinator.cancel_all(timeout_s=1.0)

    assert lingering == [stubborn]
    assert coordinator.tasks == [stubborn]
    assert "stubborn-background" in caplog.text
    assert "remain pending" in caplog.text

    stubborn.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stubborn


@pytest.mark.asyncio
async def test_retain_pending_drops_completed_tasks() -> None:
    coordinator = BackgroundTaskCoordinator(
        monitor_task=lambda task: None,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )
    done_task = asyncio.create_task(asyncio.sleep(0), name="completed-background")
    coordinator.tasks = [done_task]

    await done_task

    assert coordinator.retain_pending() == []
    assert coordinator.tasks == []
