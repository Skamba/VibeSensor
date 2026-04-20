"""Exercise AnyIO-backed background task tracking and cancellation behavior."""

from __future__ import annotations

import asyncio
import logging

import anyio
import pytest

from vibesensor.infra.runtime.background_task_coordinator import BackgroundTaskCoordinator
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.task_supervisor import TaskSupervisor


@pytest.mark.asyncio
async def test_start_records_failure_via_task_supervisor() -> None:
    health_state = RuntimeHealthState()
    supervisor = TaskSupervisor(
        health_state=health_state,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )
    coordinator = BackgroundTaskCoordinator(
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )
    await coordinator.open()

    async def _fail() -> None:
        raise RuntimeError("boom")

    coordinator.start(
        lambda: supervisor.run(_fail, name="update-startup-recover"),
        name="update-startup-recover",
    )

    for _ in range(10):
        if "update-startup-recover" in health_state.background_task_failures:
            break
        await asyncio.sleep(0)

    assert health_state.background_task_failures["update-startup-recover"] == "boom"
    assert coordinator.tasks == []
    await coordinator.cancel_all(timeout_s=1.0)
    await coordinator.close()


@pytest.mark.asyncio
async def test_cancel_all_reports_lingering_task_names_after_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = BackgroundTaskCoordinator(
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )
    await coordinator.open()
    release = anyio.Event()

    async def _shielded_linger() -> None:
        cancelled_exc_class = anyio.get_cancelled_exc_class()
        try:
            await anyio.sleep_forever()
        except cancelled_exc_class:
            with anyio.CancelScope(shield=True):
                await release.wait()

    coordinator.start(_shielded_linger, name="stubborn-background")
    await asyncio.sleep(0)

    with caplog.at_level(logging.WARNING):
        lingering = await coordinator.cancel_all(timeout_s=0.01)

    assert lingering == ["stubborn-background"]
    assert coordinator.tasks == ["stubborn-background"]
    assert "stubborn-background" in caplog.text
    assert "remain pending" in caplog.text

    release.set()
    await coordinator.close()
    assert coordinator.tasks == []


@pytest.mark.asyncio
async def test_close_clears_finished_tasks() -> None:
    coordinator = BackgroundTaskCoordinator(
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )
    await coordinator.open()
    finished = anyio.Event()

    async def _done() -> None:
        finished.set()

    coordinator.start(_done, name="completed-background")
    await finished.wait()
    await asyncio.sleep(0)

    assert coordinator.tasks == []
    await coordinator.cancel_all(timeout_s=1.0)
    await coordinator.close()
