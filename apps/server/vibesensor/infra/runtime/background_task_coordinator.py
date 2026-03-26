"""Background task tracking and coordinated cancellation for runtime services."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine

MonitorTask = Callable[[asyncio.Task[object]], None]


class BackgroundTaskCoordinator:
    """Track lifecycle-owned background tasks and cancel them coherently."""

    __slots__ = ("_logger", "_monitor_task", "_tasks")

    def __init__(
        self,
        *,
        monitor_task: MonitorTask,
        logger: logging.Logger,
    ) -> None:
        self._monitor_task = monitor_task
        self._logger = logger
        self._tasks: list[asyncio.Task[object]] = []

    @property
    def tasks(self) -> list[asyncio.Task[object]]:
        return self._tasks

    @tasks.setter
    def tasks(self, tasks: list[asyncio.Task[object]]) -> None:
        self._tasks = tasks

    def add(self, task: asyncio.Task[object]) -> asyncio.Task[object]:
        self._tasks.append(task)
        return task

    def start(
        self,
        coroutine: Coroutine[object, object, object],
        *,
        name: str,
    ) -> asyncio.Task[object]:
        task = asyncio.create_task(coroutine, name=name)
        self._monitor_task(task)
        return self.add(task)

    def retain_pending(self) -> list[asyncio.Task[object]]:
        self._tasks = [task for task in self._tasks if not task.done()]
        return list(self._tasks)

    async def cancel_all(self, *, timeout_s: float) -> list[asyncio.Task[object]]:
        for task in self._tasks:
            task.cancel()
        if not self._tasks:
            return []
        _done, pending = await asyncio.wait(self._tasks, timeout=timeout_s)
        if pending:
            self._logger.warning(
                "%d background task(s) did not finish within the cancellation "
                "deadline and remain pending: %s",
                len(pending),
                [task.get_name() for task in pending],
            )
        return self.retain_pending()
