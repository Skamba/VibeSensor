"""Exercise supervised task restart, terminal failure recording, and backoff caps."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from unittest.mock import patch

import pytest

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.task_supervisor import TaskSupervisor


@pytest.mark.asyncio
async def test_supervisor_restarts_failed_task_and_clears_health(monkeypatch) -> None:
    import vibesensor.infra.runtime.task_supervisor as task_supervisor_module

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

    monkeypatch.setattr(task_supervisor_module.asyncio, "sleep", _fast_sleep)

    task = supervisor.start(task_factory, name="ws-broadcast")
    await asyncio.wait_for(restart_started.wait(), timeout=1.0)

    assert call_count == 2
    assert health_state.background_task_failures == {}

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_supervisor_restarts_unexpected_exit(monkeypatch) -> None:
    import vibesensor.infra.runtime.task_supervisor as task_supervisor_module

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
            return
        restart_started.set()
        await asyncio.Future()

    monkeypatch.setattr(task_supervisor_module.asyncio, "sleep", _fast_sleep)

    task = supervisor.start(task_factory, name="metrics-log")
    await asyncio.wait_for(restart_started.wait(), timeout=1.0)

    assert call_count == 2
    assert health_state.background_task_failures == {}

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


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

    task = supervisor.start(task_factory, name="processing-loop")
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

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
        patch("vibesensor.infra.runtime.task_supervisor.asyncio.sleep", side_effect=_fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        task = supervisor.start(task_factory, name="gps-speed")
        await task

    assert sleep_calls == [1.0, 2.0, 2.0]
