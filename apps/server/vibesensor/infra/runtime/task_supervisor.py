"""Managed-task supervision with restart/backoff policy for runtime services."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

import anyio
from opentelemetry.trace import SpanKind, Status, StatusCode

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.tracing import mark_span_error, start_span

__all__ = ["TaskSupervisor", "task_failure_message"]

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
