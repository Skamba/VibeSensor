from __future__ import annotations

import asyncio
import contextlib

import pytest

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.job_executor import UpdateJobExecutor


@pytest.mark.asyncio
async def test_start_rejects_concurrent_job() -> None:
    executor = UpdateJobExecutor()
    started = asyncio.Event()
    release = asyncio.Event()

    async def running_job() -> None:
        started.set()
        await release.wait()

    executor.start(lambda: running_job())
    task = executor.job_task
    assert task is not None
    await asyncio.wait_for(started.wait(), timeout=1)

    with pytest.raises(UpdateError, match="already in progress"):
        executor.start(lambda: running_job())

    executor.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_sets_event_and_cancels_running_task() -> None:
    executor = UpdateJobExecutor()
    started = asyncio.Event()

    async def running_job() -> None:
        started.set()
        await asyncio.Event().wait()

    executor.start(lambda: running_job())
    task = executor.job_task
    assert task is not None
    await asyncio.wait_for(started.wait(), timeout=1)

    assert executor.cancel_requested() is False
    assert executor.cancel() is True
    assert executor.cancel_requested() is True
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_run_timeout_calls_timeout_handler_and_cleanup() -> None:
    executor = UpdateJobExecutor()
    events: list[str] = []

    async def slow_workflow() -> None:
        await asyncio.sleep(1)

    async def cleanup() -> None:
        events.append("cleanup")

    await executor.run(
        workflow_factory=lambda: slow_workflow(),
        timeout_s=0.01,
        on_timeout=lambda: events.append("timeout"),
        on_cancelled=lambda: events.append("cancelled"),
        cleanup=cleanup,
        on_cleanup_error=lambda exc: events.append(f"cleanup-error:{type(exc).__name__}"),
    )

    assert events == ["timeout", "cleanup"]


@pytest.mark.asyncio
async def test_run_surfaces_cancelled_cleanup_error() -> None:
    executor = UpdateJobExecutor()
    events: list[str] = []

    async def cancelled_workflow() -> None:
        raise asyncio.CancelledError()

    async def cleanup() -> None:
        events.append("cleanup")
        raise RuntimeError("cleanup bug")

    with pytest.raises(UpdateCleanupError, match="Cleanup failed: cleanup bug"):
        await executor.run(
            workflow_factory=lambda: cancelled_workflow(),
            timeout_s=1.0,
            on_timeout=lambda: events.append("timeout"),
            on_cancelled=lambda: events.append("cancelled"),
            cleanup=cleanup,
            on_cleanup_error=lambda exc: events.append(f"cleanup-error:{type(exc).__name__}"),
        )

    assert events == ["cancelled", "cleanup", "cleanup-error:RuntimeError"]


@pytest.mark.asyncio
async def test_run_reraises_unexpected_error_after_reporting_and_cleanup() -> None:
    executor = UpdateJobExecutor()
    events: list[str] = []

    async def broken_workflow() -> None:
        raise RuntimeError("workflow bug")

    async def cleanup() -> None:
        events.append("cleanup")

    with pytest.raises(RuntimeError, match="workflow bug"):
        await executor.run(
            workflow_factory=lambda: broken_workflow(),
            timeout_s=1.0,
            on_timeout=lambda: events.append("timeout"),
            on_cancelled=lambda: events.append("cancelled"),
            cleanup=cleanup,
            on_cleanup_error=lambda exc: events.append(f"cleanup-error:{type(exc).__name__}"),
        )

    assert events == ["cleanup"]


@pytest.mark.asyncio
async def test_run_preserves_workflow_error_when_cleanup_also_fails() -> None:
    executor = UpdateJobExecutor()
    events: list[str] = []

    async def broken_workflow() -> None:
        raise RuntimeError("workflow bug")

    async def cleanup() -> None:
        events.append("cleanup")
        raise RuntimeError("cleanup bug")

    with pytest.raises(RuntimeError, match="workflow bug"):
        await executor.run(
            workflow_factory=lambda: broken_workflow(),
            timeout_s=1.0,
            on_timeout=lambda: events.append("timeout"),
            on_cancelled=lambda: events.append("cancelled"),
            cleanup=cleanup,
            on_cleanup_error=lambda exc: events.append(f"cleanup-error:{type(exc).__name__}"),
        )

    assert events == ["cleanup", "cleanup-error:RuntimeError"]
