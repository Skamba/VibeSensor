"""Supervised restart/backoff and task-group tracking/cancellation for background tasks."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from unittest.mock import patch

import anyio
import pytest

from vibesensor.infra.runtime.background_tasks import BackgroundTaskCoordinator, TaskSupervisor
from vibesensor.infra.runtime.health_state import RuntimeHealthState


@pytest.mark.asyncio
async def test_supervisor_restarts_failed_task_and_clears_health() -> None:
    health_state = RuntimeHealthState()
    supervisor = TaskSupervisor(
        health_state=health_state,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
        base_delay_s=0.0,
        max_delay_s=0.0,
    )
    restart_started = asyncio.Event()
    call_count = 0
    original_sleep = asyncio.sleep

    async def _fast_sleep(delay: float) -> None:
        del delay
        await original_sleep(0)

    async def task_factory() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        restart_started.set()
        await asyncio.Future()

    with patch("vibesensor.infra.runtime.background_tasks.anyio.sleep", side_effect=_fast_sleep):
        task = asyncio.create_task(
            supervisor.run(
                task_factory,
                name="ws-broadcast",
                restartable_exceptions=(RuntimeError,),
            )
        )
        try:
            await asyncio.wait_for(restart_started.wait(), timeout=1.0)
            assert call_count == 2
            assert health_state.background_task_failures == {}
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_supervisor_treats_unexpected_exit_as_terminal_failure() -> None:
    health_state = RuntimeHealthState()
    supervisor = TaskSupervisor(
        health_state=health_state,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
        base_delay_s=0.0,
        max_delay_s=0.0,
    )
    call_count = 0

    async def task_factory() -> None:
        nonlocal call_count
        call_count += 1

    await supervisor.run(
        task_factory,
        name="metrics-log",
        restartable_exceptions=(RuntimeError,),
    )

    assert call_count == 1
    assert (
        health_state.background_task_failures["metrics-log"]
        == "managed task metrics-log exited unexpectedly"
    )


@pytest.mark.asyncio
async def test_supervisor_records_terminal_failure_after_max_attempts() -> None:
    health_state = RuntimeHealthState()
    supervisor = TaskSupervisor(
        health_state=health_state,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
        max_attempts=0,
    )

    async def task_factory() -> None:
        raise RuntimeError("boom")

    await supervisor.run(task_factory, name="processing-loop")

    assert health_state.background_task_failures["processing-loop"] == "boom"


@pytest.mark.asyncio
async def test_supervisor_caps_restart_delay() -> None:
    health_state = RuntimeHealthState()
    supervisor = TaskSupervisor(
        health_state=health_state,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
        max_attempts=10,
        base_delay_s=1.0,
        max_delay_s=2.0,
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        if len(sleep_calls) >= 3:
            raise asyncio.CancelledError

    async def task_factory() -> None:
        raise RuntimeError("boom")

    with (
        patch("vibesensor.infra.runtime.background_tasks.anyio.sleep", side_effect=_fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await supervisor.run(
            task_factory,
            name="gps-speed",
            restartable_exceptions=(RuntimeError,),
        )

    assert sleep_calls == [1.0, 2.0, 2.0]


@pytest.mark.asyncio
async def test_supervisor_does_not_restart_unclassified_exception() -> None:
    health_state = RuntimeHealthState()
    supervisor = TaskSupervisor(
        health_state=health_state,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
        base_delay_s=0.0,
        max_delay_s=0.0,
    )
    call_count = 0

    async def task_factory() -> None:
        nonlocal call_count
        call_count += 1
        raise TypeError("bug")

    await supervisor.run(
        task_factory,
        name="obd-speed",
        restartable_exceptions=(RuntimeError,),
    )

    assert call_count == 1
    assert health_state.background_task_failures["obd-speed"] == "bug"


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
