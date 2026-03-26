"""Tests for ManagedJobShutdown (#1449)."""

from __future__ import annotations

import asyncio

import pytest

from vibesensor.infra.runtime.managed_job_shutdown import ManagedJobShutdown


class _FakeJobSource:
    def __init__(self, task: asyncio.Task[None] | None = None) -> None:
        self._task = task

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._task


class TestManagedJobShutdown:
    """Verify managed-job shutdown ignores inactive sources and cancels active tasks."""

    @pytest.mark.asyncio
    async def test_no_active_tasks_returns_empty(self) -> None:
        """Sources with no active tasks produce an empty lingering list."""
        shutdown = ManagedJobShutdown(
            [
                _FakeJobSource(None),
                _FakeJobSource(None),
            ]
        )
        lingering = await shutdown.cancel(timeout_s=5.0)
        assert lingering == []

    @pytest.mark.asyncio
    async def test_cancels_active_tasks(self) -> None:
        """Active tasks get cancelled and finish within timeout."""

        async def slow_job() -> None:
            await asyncio.sleep(100)

        task = asyncio.create_task(slow_job(), name="test-update-job")
        shutdown = ManagedJobShutdown([_FakeJobSource(task)])
        lingering = await shutdown.cancel(timeout_s=5.0)
        assert lingering == []
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_done_tasks_ignored(self) -> None:
        """Already-done tasks are not included in cancellation."""

        async def instant_job() -> None:
            pass

        task = asyncio.create_task(instant_job(), name="test-done-job")
        await task  # let it finish
        shutdown = ManagedJobShutdown([_FakeJobSource(task)])
        lingering = await shutdown.cancel(timeout_s=5.0)
        assert lingering == []

    @pytest.mark.asyncio
    async def test_mixed_sources(self) -> None:
        """Mix of None, done, and active tasks — only active gets cancelled."""

        async def slow_job() -> None:
            await asyncio.sleep(100)

        async def instant_job() -> None:
            pass

        done_task = asyncio.create_task(instant_job(), name="done")
        await done_task
        active_task = asyncio.create_task(slow_job(), name="active")

        shutdown = ManagedJobShutdown(
            [
                _FakeJobSource(None),
                _FakeJobSource(done_task),
                _FakeJobSource(active_task),
            ]
        )
        lingering = await shutdown.cancel(timeout_s=5.0)
        assert lingering == []
        assert active_task.cancelled()
