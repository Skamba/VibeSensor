"""Exercise supervised service restart, terminal failure recording, and backoff caps."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from unittest.mock import patch

import pytest

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.task_supervisor import TaskSupervisor


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

    with patch("vibesensor.infra.runtime.task_supervisor.anyio.sleep", side_effect=_fast_sleep):
        task = asyncio.create_task(
            supervisor.run(
                task_factory,
                name="ws-broadcast",
                restartable_exceptions=(RuntimeError,),
            )
        )
        await asyncio.wait_for(restart_started.wait(), timeout=1.0)
        assert call_count == 2
        assert health_state.background_task_failures == {}
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
        patch("vibesensor.infra.runtime.task_supervisor.anyio.sleep", side_effect=_fake_sleep),
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
