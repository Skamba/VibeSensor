"""Retry, backoff, and escalation policy for runtime processing failures."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import anyio

from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.runtime_failures import ProcessingLoopFailure

from .processing_failures import ProcessingTickFailure
from .processing_state import ProcessingHealth

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
    "ProcessingFailureDecision",
    "ProcessingFailurePolicy",
    "ProcessingSuccessDecision",
]


@dataclass(frozen=True, slots=True)
class ProcessingSuccessDecision:
    """State update emitted after one successful processing tick."""

    tick_duration_s: float


@dataclass(frozen=True, slots=True)
class ProcessingFailureDecision:
    """State update and backoff plan emitted after one failed processing tick."""

    failure_category: str
    failure_message: str
    next_delay_s: float
    processing_state: ProcessingHealth
    backoff_sleep_s: float | None = None
    post_backoff_state: ProcessingHealth | None = None
    escalation_failure: ProcessingLoopFailure | None = None


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

    def plan_success(self, *, tick_duration_s: float) -> ProcessingSuccessDecision:
        self._consecutive_failures = 0
        self._fatal_backoff_cycles = 0
        return ProcessingSuccessDecision(tick_duration_s=tick_duration_s)

    def plan_failure(
        self,
        failure: ProcessingTickFailure,
        *,
        interval_s: float,
    ) -> ProcessingFailureDecision:
        self._consecutive_failures += 1
        category = failure.category.value
        failure_message = bounded_failure_message(
            failure.cause,
            max_length=_MAX_FAILURE_MESSAGE_LEN,
        )
        is_fatal = self._consecutive_failures >= self._max_consecutive_failures
        self._logger.warning(
            "Processing loop tick failed in %s; will retry.",
            category,
            exc_info=(type(failure.cause), failure.cause, failure.cause.__traceback__),
        )
        if is_fatal:
            return self._plan_fatal_backoff(
                failure,
                category=category,
                failure_message=failure_message,
                interval_s=interval_s,
            )
        retry_delay_s = interval_s * float(
            2 ** min(_MAX_BACKOFF_EXPONENT, self._consecutive_failures)
        )
        return ProcessingFailureDecision(
            failure_category=category,
            failure_message=failure_message,
            next_delay_s=(
                self._max_retry_delay_s
                if retry_delay_s > self._max_retry_delay_s
                else retry_delay_s
            ),
            processing_state=ProcessingHealth.DEGRADED,
        )

    def _plan_fatal_backoff(
        self,
        failure: ProcessingTickFailure,
        *,
        category: str,
        failure_message: str,
        interval_s: float,
    ) -> ProcessingFailureDecision:
        self._fatal_backoff_cycles += 1
        if self._fatal_backoff_cycles >= self._max_fatal_backoff_cycles:
            self._logger.error(
                "Processing loop exceeded %d fatal backoff cycles; "
                "escalating to a managed task failure.",
                self._max_fatal_backoff_cycles,
            )
            return ProcessingFailureDecision(
                failure_category=category,
                failure_message=failure_message,
                next_delay_s=0.0,
                processing_state=ProcessingHealth.FATAL,
                escalation_failure=ProcessingLoopFailure(
                    fatal_backoff_cycles=self._fatal_backoff_cycles,
                    failure_category=failure.category.value,
                    cause=failure.cause,
                ),
            )
        self._logger.error(
            "Processing loop hit %d failures; backing off %s s (fatal cycle %d/%d)",
            self._max_consecutive_failures,
            self._failure_backoff_s,
            self._fatal_backoff_cycles,
            self._max_fatal_backoff_cycles,
        )
        self._consecutive_failures = 0
        return ProcessingFailureDecision(
            failure_category=category,
            failure_message=failure_message,
            next_delay_s=interval_s,
            processing_state=ProcessingHealth.FATAL,
            backoff_sleep_s=self._failure_backoff_s,
            post_backoff_state=ProcessingHealth.DEGRADED,
        )

    async def complete_backoff(
        self,
        *,
        cycle: int,
        total_failure_count: int,
    ) -> None:
        await anyio.sleep(self._failure_backoff_s)
        self._logger.info(
            "Processing loop resuming after fatal-backoff cycle %d/%d; "
            "total failure count so far: %d",
            cycle,
            self._max_fatal_backoff_cycles,
            total_failure_count,
        )
