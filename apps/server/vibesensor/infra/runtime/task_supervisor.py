"""Managed task supervision with restart/backoff policy for runtime services."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine

from opentelemetry.trace import SpanKind, Status, StatusCode

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.tracing import mark_span_error, start_span

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
        """Create a supervised task that restarts only on declared failures."""

        async def _run_supervised() -> None:
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
                    except asyncio.CancelledError:
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
                            raise
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
                        await asyncio.sleep(delay_s)
                        self._health_state.clear_task_failure(name)
                        continue
                    runtime_s = time.monotonic() - started_at
                    span.set_attribute("vibesensor.runtime_s", round(runtime_s, 3))
                    span.set_attribute("vibesensor.unexpected_exit", True)
                    span.set_status(Status(StatusCode.ERROR, "managed task exited unexpectedly"))
                raise RuntimeError(f"managed task {name} exited unexpectedly")

        task = asyncio.create_task(_run_supervised(), name=name)
        self.monitor_task(task)
        return task
