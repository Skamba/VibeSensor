"""Retry, backoff, and escalation policy for runtime processing failures."""

from __future__ import annotations

import asyncio
import logging

from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.runtime_failures import ProcessingLoopFailure

from .processing_failures import ProcessingTickFailure
from .processing_state import ProcessingHealth, ProcessingLoopState

MAX_CONSECUTIVE_FAILURES = 25
"""After this many consecutive processing failures, enter fatal backoff."""

FAILURE_BACKOFF_S = 5
"""Seconds to sleep on fatal failure threshold before retrying the loop."""

MAX_FATAL_BACKOFF_CYCLES = 3
"""After this many fatal backoff cycles, escalate to a managed task failure."""

_MAX_FAILURE_MESSAGE_LEN = 240
_MAX_RETRY_DELAY_S = 5.0
_MAX_BACKOFF_EXPONENT = 6

__all__ = [
    "FAILURE_BACKOFF_S",
    "MAX_CONSECUTIVE_FAILURES",
    "MAX_FATAL_BACKOFF_CYCLES",
    "ProcessingFailurePolicy",
]


class ProcessingFailurePolicy:
    """Own categorized failure accounting, retry delay, and fatal escalation."""

    __slots__ = (
        "_consecutive_failures",
        "_failure_backoff_s",
        "_fatal_backoff_cycles",
        "_logger",
        "_max_consecutive_failures",
        "_max_fatal_backoff_cycles",
        "_max_retry_delay_s",
    )

    def __init__(
        self,
        *,
        logger: logging.Logger,
        max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
        failure_backoff_s: float = FAILURE_BACKOFF_S,
        max_fatal_backoff_cycles: int = MAX_FATAL_BACKOFF_CYCLES,
        max_retry_delay_s: float = _MAX_RETRY_DELAY_S,
    ) -> None:
        self._logger = logger
        self._max_consecutive_failures = max_consecutive_failures
        self._failure_backoff_s = failure_backoff_s
        self._max_fatal_backoff_cycles = max_fatal_backoff_cycles
        self._max_retry_delay_s = max_retry_delay_s
        self._consecutive_failures = 0
        self._fatal_backoff_cycles = 0

    @property
    def fatal_backoff_cycles(self) -> int:
        return self._fatal_backoff_cycles

    def record_success(self, state: ProcessingLoopState, *, tick_duration_s: float) -> None:
        state.last_tick_duration_s = tick_duration_s
        if tick_duration_s > state.max_tick_duration_s:
            state.max_tick_duration_s = tick_duration_s
        state.tick_count += 1
        state.processing_state = ProcessingHealth.OK
        self._consecutive_failures = 0
        self._fatal_backoff_cycles = 0

    async def record_failure(
        self,
        state: ProcessingLoopState,
        failure: ProcessingTickFailure,
        *,
        interval_s: float,
    ) -> float:
        self._consecutive_failures += 1
        category = failure.category.value
        state.processing_failure_count += 1
        state.last_failure_category = category
        state.last_failure_message = bounded_failure_message(
            failure.cause,
            max_length=_MAX_FAILURE_MESSAGE_LEN,
        )
        state.processing_failure_categories[category] = (
            state.processing_failure_categories.get(category, 0) + 1
        )
        is_fatal = self._consecutive_failures >= self._max_consecutive_failures
        state.processing_state = ProcessingHealth.FATAL if is_fatal else ProcessingHealth.DEGRADED
        self._logger.warning(
            "Processing loop tick failed in %s; will retry.",
            category,
            exc_info=(type(failure.cause), failure.cause, failure.cause.__traceback__),
        )
        if is_fatal:
            return await self._handle_fatal_backoff(state, failure, interval_s=interval_s)
        retry_delay_s = interval_s * float(
            2 ** min(_MAX_BACKOFF_EXPONENT, self._consecutive_failures)
        )
        return self._max_retry_delay_s if retry_delay_s > self._max_retry_delay_s else retry_delay_s

    async def _handle_fatal_backoff(
        self,
        state: ProcessingLoopState,
        failure: ProcessingTickFailure,
        *,
        interval_s: float,
    ) -> float:
        self._fatal_backoff_cycles += 1
        if self._fatal_backoff_cycles >= self._max_fatal_backoff_cycles:
            self._logger.error(
                "Processing loop exceeded %d fatal backoff cycles; "
                "escalating to a managed task failure.",
                self._max_fatal_backoff_cycles,
            )
            raise ProcessingLoopFailure(
                fatal_backoff_cycles=self._fatal_backoff_cycles,
                failure_category=failure.category.value,
                cause=failure.cause,
            ) from failure.cause
        self._logger.error(
            "Processing loop hit %d failures; backing off %s s (fatal cycle %d/%d)",
            self._max_consecutive_failures,
            self._failure_backoff_s,
            self._fatal_backoff_cycles,
            self._max_fatal_backoff_cycles,
        )
        await asyncio.sleep(self._failure_backoff_s)
        state.processing_state = ProcessingHealth.DEGRADED
        self._logger.info(
            "Processing loop resuming after fatal-backoff cycle %d/%d; "
            "total failure count so far: %d",
            self._fatal_backoff_cycles,
            self._max_fatal_backoff_cycles,
            state.processing_failure_count,
        )
        self._consecutive_failures = 0
        return interval_s
