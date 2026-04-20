"""Background task tracking and coordinated cancellation for runtime services."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

import anyio
from anyio.abc import TaskGroup

TaskFactory = Callable[[], Awaitable[object]]


class BackgroundTaskCoordinator:
    """Own the lifecycle-scoped AnyIO task group for background services."""

    __slots__ = (
        "_active_names",
        "_all_done",
        "_logger",
        "_task_group",
        "_task_group_cm",
        "_task_scopes",
    )

    def __init__(
        self,
        *,
        logger: logging.Logger,
    ) -> None:
        self._logger = logger
        self._active_names: set[str] = set()
        self._all_done = anyio.Event()
        self._all_done.set()
        self._task_group: TaskGroup | None = None
        self._task_group_cm: AbstractAsyncContextManager[TaskGroup] | None = None
        self._task_scopes: dict[str, anyio.CancelScope] = {}

    @property
    def tasks(self) -> list[str]:
        return sorted(self._active_names)

    async def open(self) -> None:
        if self._task_group is not None:
            return
        self._task_group_cm = anyio.create_task_group()
        self._task_group = await self._task_group_cm.__aenter__()

    async def close(self) -> None:
        if self._task_group_cm is None:
            return
        await self._task_group_cm.__aexit__(None, None, None)
        self._task_group = None
        self._task_group_cm = None

    async def _run_tracked(
        self,
        task_factory: TaskFactory,
        name: str,
    ) -> None:
        cancelled_exc_class = anyio.get_cancelled_exc_class()
        if not self._active_names:
            self._all_done = anyio.Event()
        with anyio.CancelScope() as cancel_scope:
            self._active_names.add(name)
            self._task_scopes[name] = cancel_scope
            try:
                try:
                    await task_factory()
                except cancelled_exc_class:
                    return
            finally:
                self._task_scopes.pop(name, None)
                self._active_names.discard(name)
                if not self._active_names:
                    self._all_done.set()

    def start(
        self,
        task_factory: TaskFactory,
        *,
        name: str,
    ) -> None:
        if self._task_group is None:
            raise RuntimeError("BackgroundTaskCoordinator.start() called before open()")
        self._task_group.start_soon(self._run_tracked, task_factory, name, name=name)

    async def cancel_all(self, *, timeout_s: float) -> list[str]:
        if self._task_group is None:
            return []
        for cancel_scope in list(self._task_scopes.values()):
            cancel_scope.cancel()
        with anyio.move_on_after(timeout_s) as scope:
            await self._all_done.wait()
        lingering = self.tasks if scope.cancel_called else []
        if lingering:
            self._logger.warning(
                "%d background task(s) did not finish within the cancellation "
                "deadline and remain pending: %s",
                len(lingering),
                lingering,
            )
        return lingering
