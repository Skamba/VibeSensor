"""Tests for ManagedJobShutdown (#1449)."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import pytest

from vibesensor.infra.runtime.managed_job_shutdown import ManagedJobShutdown


class _FakeJobSource:
    def __init__(self, task: asyncio.Task[None] | None = None) -> None:
        self._task = task

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._task


async def _slow_job() -> None:
    await asyncio.sleep(100)


async def _stubborn_job() -> None:
    first_wait = asyncio.Event()
    second_wait = asyncio.Event()
    try:
        await first_wait.wait()
    except asyncio.CancelledError:
        await second_wait.wait()


async def _instant_job() -> None:
    return None


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
        task = asyncio.create_task(_slow_job(), name="test-update-job")
        shutdown = ManagedJobShutdown([_FakeJobSource(task)])
        lingering = await shutdown.cancel(timeout_s=5.0)
        assert lingering == []
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_done_tasks_ignored(self) -> None:
        """Already-done tasks are not included in cancellation."""
        task = asyncio.create_task(_instant_job(), name="test-done-job")
        await task  # let it finish
        shutdown = ManagedJobShutdown([_FakeJobSource(task)])
        lingering = await shutdown.cancel(timeout_s=5.0)
        assert lingering == []

    @pytest.mark.asyncio
    async def test_mixed_sources(self) -> None:
        """Mix of None, done, and active tasks — only active gets cancelled."""
        done_task = asyncio.create_task(_instant_job(), name="done")
        await done_task
        active_task = asyncio.create_task(_slow_job(), name="active")

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

    @pytest.mark.asyncio
    async def test_lingering_tasks_returned_and_logged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Tasks that outlive cancellation are returned and logged by name."""
        import vibesensor.infra.runtime.managed_job_shutdown as shutdown_module

        task = asyncio.create_task(_stubborn_job(), name="stubborn-job")
        await asyncio.sleep(0)

        async def _wait_pending(
            tasks: list[asyncio.Task[None]],
            timeout: float | None,
        ) -> tuple[set[asyncio.Task[None]], set[asyncio.Task[None]]]:
            del timeout
            await asyncio.sleep(0)
            return set(), set(tasks)

        monkeypatch.setattr(shutdown_module.asyncio, "wait", _wait_pending)
        shutdown = ManagedJobShutdown([_FakeJobSource(task)])

        try:
            with caplog.at_level(logging.WARNING, logger=shutdown_module.LOGGER.name):
                lingering = await shutdown.cancel(timeout_s=0.01)

            assert lingering == [task]
            assert "managed shutdown task(s)" in caplog.text
            assert "stubborn-job" in caplog.text
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
