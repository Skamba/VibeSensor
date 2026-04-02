"""Managed task supervision with restart/backoff policy for runtime services."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.shared.failure_utils import bounded_failure_message

__all__ = ["TaskSupervisor", "task_failure_message"]

TaskFactory = Callable[[], Coroutine[object, object, object]]
RestartableExceptions = tuple[type[Exception], ...]

_TASK_RESTART_MAX_ATTEMPTS = 3
_TASK_RESTART_BASE_DELAY_S = 1.0
_TASK_RESTART_MAX_DELAY_S = 10.0
_TASK_RESTART_RESET_AFTER_S = 60.0


def task_failure_message(exc: BaseException) -> str:
    """Normalize a task failure into a bounded health-state message."""

    return bounded_failure_message(exc, max_length=240)


class TaskSupervisor:
    """Create managed tasks that restart with exponential backoff on failure."""

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

    def monitor_task(self, task: asyncio.Task[object]) -> None:
        task_name = task.get_name()
        recorded = False

        def _record_failure(done_task: asyncio.Task[object]) -> None:
            nonlocal recorded
            if recorded:
                return
            recorded = True
            if done_task.cancelled():
                return
            try:
                exc = done_task.exception()
            except asyncio.CancelledError:
                return
            if exc is None:
                return
            message = task_failure_message(exc)
            self._health_state.record_task_failure(task_name, message)
            self._logger.error("Managed task %s failed: %s", task_name, message, exc_info=exc)

        task.add_done_callback(_record_failure)
        if task.done():
            _record_failure(task)

    def _restart_delay_s(self, restart_count: int) -> float:
        exponent = max(0, restart_count - 1)
        return float(min(self._max_delay_s, self._base_delay_s * (2**exponent)))

    def start(
        self,
        task_factory: TaskFactory,
        *,
        name: str,
        restartable_exceptions: RestartableExceptions = (),
    ) -> asyncio.Task[object]:
        """Create a supervised task that restarts on declared failures or unexpected exit."""

        async def _run_supervised() -> None:
            restart_count = 0
            while True:
                started_at = time.monotonic()
                try:
                    await task_factory()
                except asyncio.CancelledError:
                    raise
                except restartable_exceptions as exc:
                    runtime_s = time.monotonic() - started_at
                    if runtime_s >= self._reset_after_s:
                        restart_count = 0
                    if restart_count >= self._max_attempts:
                        raise
                    restart_count += 1
                    delay_s = self._restart_delay_s(restart_count)
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
                    await asyncio.sleep(delay_s)
                    self._health_state.clear_task_failure(name)
                    continue

                runtime_s = time.monotonic() - started_at
                if runtime_s >= self._reset_after_s:
                    restart_count = 0
                unexpected_exit = RuntimeError(f"managed task {name} exited unexpectedly")
                if restart_count >= self._max_attempts:
                    raise unexpected_exit
                restart_count += 1
                delay_s = self._restart_delay_s(restart_count)
                self._health_state.record_task_failure(
                    name,
                    task_failure_message(unexpected_exit),
                )
                self._logger.error(
                    "Managed task %s exited unexpectedly; restarting in %.1fs (%d/%d).",
                    name,
                    delay_s,
                    restart_count,
                    self._max_attempts,
                )
                await asyncio.sleep(delay_s)
                self._health_state.clear_task_failure(name)

        task = asyncio.create_task(_run_supervised(), name=name)
        self.monitor_task(task)
        return task
