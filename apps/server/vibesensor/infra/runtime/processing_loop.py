"""ProcessingLoop – async tick loop with failure tracking.

Owns:
- ``ProcessingLoopState`` dataclass (failure counters + mismatch guards)
- The ~100 ms tick coroutine that evicts stale clients and computes metrics
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.ports import ClockSyncBroadcaster

from .processing_tick import ProcessingLoopError, ProcessingTickRunner

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry

LOGGER = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 25
"""After this many consecutive processing failures, enter fatal backoff."""

FAILURE_BACKOFF_S = 5
"""Seconds to sleep on fatal failure threshold before resetting."""

MAX_FATAL_BACKOFF_CYCLES = 3
"""After this many fatal backoff cycles, escalate to a managed task failure."""

_MAX_FAILURE_MESSAGE_LEN = 240


class ProcessingHealth(StrEnum):
    """Health status of the processing loop."""

    OK = "ok"
    DEGRADED = "degraded"
    FATAL = "fatal"


@dataclass(slots=True)
class ProcessingLoopState:
    """Mutable tracking state for the processing loop.

    Failure counters and mismatch log-guards form a coherent,
    narrowly-scoped unit.
    """

    processing_state: ProcessingHealth = ProcessingHealth.OK
    processing_failure_count: int = 0
    processing_failure_categories: dict[str, int] = field(default_factory=dict)
    last_failure_category: str | None = None
    last_failure_message: str | None = None
    sample_rate_mismatch_logged: set[str] = field(default_factory=set)
    frame_size_mismatch_logged: set[str] = field(default_factory=set)
    last_tick_duration_s: float = 0.0
    max_tick_duration_s: float = 0.0
    tick_count: int = 0
    fatal_backoff_cycles: int = 0


class ProcessingLoop:
    """Async processing tick loop: evict stale clients, compute metrics, handle failures."""

    __slots__ = (
        "_fft_update_hz",
        "_tick_runner",
        "state",
    )

    def __init__(
        self,
        *,
        state: ProcessingLoopState,
        fft_update_hz: int,
        sample_rate_hz: int,
        fft_n: int,
        registry: ClientRegistry,
        processor: SignalProcessor,
        control_plane: ClockSyncBroadcaster | None = None,
    ) -> None:
        self.state = state
        self._fft_update_hz = fft_update_hz
        self._tick_runner = ProcessingTickRunner(
            state=state,
            sample_rate_hz=sample_rate_hz,
            fft_n=fft_n,
            registry=registry,
            processor=processor,
            control_plane=control_plane,
        )

    @staticmethod
    def _truncate_failure_message(exc: Exception) -> str:
        return bounded_failure_message(exc, max_length=_MAX_FAILURE_MESSAGE_LEN)

    def _record_failure(self, category: str, exc: Exception) -> None:
        state = self.state
        state.processing_failure_count += 1
        state.last_failure_category = category
        state.last_failure_message = self._truncate_failure_message(exc)
        state.processing_failure_categories[category] = (
            state.processing_failure_categories.get(category, 0) + 1
        )

    async def _handle_fatal_backoff(self) -> int:
        state = self.state
        state.fatal_backoff_cycles += 1
        if state.fatal_backoff_cycles >= MAX_FATAL_BACKOFF_CYCLES:
            message = (
                "persistent processing failure after "
                f"{state.fatal_backoff_cycles} fatal backoff cycles"
            )
            LOGGER.error(
                "Processing loop exceeded %d fatal backoff cycles; escalating to a "
                "managed task failure.",
                MAX_FATAL_BACKOFF_CYCLES,
            )
            raise RuntimeError(message)
        LOGGER.error(
            "Processing loop hit %d failures; backing off %d s (fatal cycle %d/%d)",
            MAX_CONSECUTIVE_FAILURES,
            FAILURE_BACKOFF_S,
            state.fatal_backoff_cycles,
            MAX_FATAL_BACKOFF_CYCLES,
        )
        await asyncio.sleep(FAILURE_BACKOFF_S)
        state.processing_state = ProcessingHealth.DEGRADED
        LOGGER.info(
            "Processing loop resuming after fatal-backoff cycle %d/%d; "
            "total failure count so far: %d",
            state.fatal_backoff_cycles,
            MAX_FATAL_BACKOFF_CYCLES,
            state.processing_failure_count,
        )
        return 0

    async def _run_tick(self, *, sync_clock: bool) -> None:
        await self._tick_runner.run(sync_clock=sync_clock)

    async def run(self) -> None:
        """~100 ms tick loop: evict stale clients, compute metrics, handle failures."""
        interval = 1.0 / max(1, self._fft_update_hz)
        consecutive_failures = 0
        _sync_clock_tick = 0
        _SYNC_CLOCK_EVERY_N_TICKS = max(1, int(5.0 / interval))  # ~every 5 s
        while True:
            try:
                _sync_clock_tick += 1
                sync_clock = False
                if _sync_clock_tick >= _SYNC_CLOCK_EVERY_N_TICKS:
                    _sync_clock_tick = 0
                    sync_clock = True
                tick_start = time.monotonic()
                await self._run_tick(sync_clock=sync_clock)
                tick_dur = time.monotonic() - tick_start
                self.state.last_tick_duration_s = tick_dur
                if tick_dur > self.state.max_tick_duration_s:
                    self.state.max_tick_duration_s = tick_dur
                self.state.tick_count += 1
                consecutive_failures = 0
                self.state.processing_state = ProcessingHealth.OK
                self.state.fatal_backoff_cycles = 0
            except ProcessingLoopError as exc:
                consecutive_failures += 1
                self._record_failure(exc.category, exc.cause)
                is_fatal = consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                self.state.processing_state = (
                    ProcessingHealth.FATAL if is_fatal else ProcessingHealth.DEGRADED
                )
                LOGGER.warning(
                    "Processing loop tick failed in %s; will retry.",
                    exc.category,
                    exc_info=True,
                )
                if is_fatal:
                    consecutive_failures = await self._handle_fatal_backoff()
            delay = (
                interval
                if consecutive_failures == 0
                else min(5.0, interval * (2 ** min(6, consecutive_failures)))
            )
            await asyncio.sleep(delay)
