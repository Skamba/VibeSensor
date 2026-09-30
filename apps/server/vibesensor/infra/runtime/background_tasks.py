"""Background-task ownership for the runtime lifecycle.

Two cooperating pieces with different jobs:

- ``BackgroundTaskCoordinator`` owns the lifecycle-scoped AnyIO task group:
  it spawns named tasks, tracks which are alive, and cancels them on shutdown.
- ``TaskSupervisor`` wraps one task body with restart/backoff policy and
  records terminal failures in ``RuntimeHealthState``.

``LifecycleManager`` starts each supervised service as
``coordinator.start(lambda: supervisor.run(factory, name=...), name=...)``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

import anyio
from anyio.abc import TaskGroup
from opentelemetry.trace import SpanKind, Status, StatusCode

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.tracing import mark_span_error, start_span

__all__ = ["BackgroundTaskCoordinator", "TaskSupervisor", "task_failure_message"]

TaskFactory = Callable[[], Awaitable[object]]
RestartableExceptions = tuple[type[Exception], ...]

_TASK_RESTART_MAX_ATTEMPTS = 3
_TASK_RESTART_BASE_DELAY_S = 1.0
_TASK_RESTART_MAX_DELAY_S = 10.0
_TASK_RESTART_RESET_AFTER_S = 60.0


def task_failure_message(exc: BaseException) -> str:
    """Normalize a task failure into a bounded health-state message."""

    return bounded_failure_message(exc, max_length=240)


class TaskSupervisor:
    """Run managed services with restart/backoff and terminal-failure recording."""

    __slots__ = (
        "_base_delay_s",
        "_health_state",
        "_logger",
        "_max_attempts",
        "_max_delay_s",
        "_reset_after_s",
    )

    def __init__(
        self,
        *,
        health_state: RuntimeHealthState,
        logger: logging.Logger,
        max_attempts: int = _TASK_RESTART_MAX_ATTEMPTS,
        base_delay_s: float = _TASK_RESTART_BASE_DELAY_S,
        max_delay_s: float = _TASK_RESTART_MAX_DELAY_S,
        reset_after_s: float = _TASK_RESTART_RESET_AFTER_S,
    ) -> None:
        self._health_state = health_state
        self._logger = logger
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._reset_after_s = reset_after_s

    def _restart_delay_s(self, restart_count: int) -> float:
        exponent = max(0, restart_count - 1)
        return float(min(self._max_delay_s, self._base_delay_s * (2**exponent)))

    def _record_terminal_failure(
        self,
        *,
        name: str,
        exc: BaseException,
    ) -> None:
        message = task_failure_message(exc)
        self._health_state.record_task_failure(name, message)
        self._logger.error("Managed task %s failed: %s", name, message, exc_info=exc)

    async def run(
        self,
        task_factory: TaskFactory,
        *,
        name: str,
        restartable_exceptions: RestartableExceptions = (),
    ) -> None:
        """Run a supervised task inline inside the owning task group."""

        cancelled_exc_class = anyio.get_cancelled_exc_class()
        restart_count = 0
        while True:
            with start_span(
                __name__,
                "runtime.managed_task",
                kind=SpanKind.INTERNAL,
                attributes={
                    "vibesensor.task.name": name,
                    "vibesensor.task.attempt": restart_count + 1,
                },
            ) as span:
                started_at = time.monotonic()
                try:
                    await task_factory()
                except cancelled_exc_class:
                    span.set_attribute("vibesensor.cancelled", True)
                    raise
                except restartable_exceptions as exc:
                    runtime_s = time.monotonic() - started_at
                    span.set_attribute("vibesensor.runtime_s", round(runtime_s, 3))
                    mark_span_error(span, exc)
                    if runtime_s >= self._reset_after_s:
                        restart_count = 0
                    if restart_count >= self._max_attempts:
                        span.set_attribute("vibesensor.restart_exhausted", True)
                        self._record_terminal_failure(name=name, exc=exc)
                        return
                    restart_count += 1
                    delay_s = self._restart_delay_s(restart_count)
                    span.set_attribute("vibesensor.restart_delay_s", delay_s)
                    self._health_state.record_task_failure(name, task_failure_message(exc))
                    self._logger.error(
                        (
                            "Managed task %s failed with restartable error; "
                            "restarting in %.1fs (%d/%d)."
                        ),
                        name,
                        delay_s,
                        restart_count,
                        self._max_attempts,
                        exc_info=exc,
                    )
                    await anyio.sleep(delay_s)
                    self._health_state.clear_task_failure(name)
                    continue
                except Exception as exc:
                    runtime_s = time.monotonic() - started_at
                    span.set_attribute("vibesensor.runtime_s", round(runtime_s, 3))
                    mark_span_error(span, exc)
                    self._record_terminal_failure(name=name, exc=exc)
                    return

                runtime_s = time.monotonic() - started_at
                span.set_attribute("vibesensor.runtime_s", round(runtime_s, 3))
                span.set_attribute("vibesensor.unexpected_exit", True)
                terminal = RuntimeError(f"managed task {name} exited unexpectedly")
                span.set_status(Status(StatusCode.ERROR, str(terminal)))
                self._record_terminal_failure(name=name, exc=terminal)
                return


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
