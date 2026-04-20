"""ProcessingLoop – async tick scheduling over tick execution and failure policy."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import anyio

from vibesensor.shared.ports import ClockSyncBroadcaster

from .processing_failure_policy import (
    ProcessingFailureDecision,
    ProcessingFailurePolicy,
    ProcessingSuccessDecision,
)
from .processing_failures import ProcessingTickFailure
from .processing_state import ProcessingHealth, ProcessingLoopState
from .processing_tick import ProcessingTickRunner

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry

LOGGER = logging.getLogger(__name__)


class ProcessingLoop:
    """Async processing tick loop: evict stale clients, compute metrics, handle failures."""

    __slots__ = (
        "_failure_policy",
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
        failure_policy: ProcessingFailurePolicy | None = None,
    ) -> None:
        self.state = state
        self._fft_update_hz = fft_update_hz
        self._failure_policy = failure_policy or ProcessingFailurePolicy(logger=LOGGER)
        self._tick_runner = ProcessingTickRunner(
            state=state,
            sample_rate_hz=sample_rate_hz,
            fft_n=fft_n,
            registry=registry,
            processor=processor,
            control_plane=control_plane,
        )

    async def _run_tick(self, *, sync_clock: bool) -> None:
        await self._tick_runner.run(sync_clock=sync_clock)

    async def run(self) -> None:
        """~100 ms tick loop: evict stale clients, compute metrics, handle failures."""
        interval = 1.0 / max(1, self._fft_update_hz)
        _sync_clock_tick = 0
        _SYNC_CLOCK_EVERY_N_TICKS = max(1, int(5.0 / interval))  # ~every 5 s
        while True:
            delay = interval
            try:
                _sync_clock_tick += 1
                sync_clock = False
                if _sync_clock_tick >= _SYNC_CLOCK_EVERY_N_TICKS:
                    _sync_clock_tick = 0
                    sync_clock = True
                tick_start = time.monotonic()
                await self._run_tick(sync_clock=sync_clock)
                tick_dur = time.monotonic() - tick_start
                self._apply_success(
                    self._failure_policy.plan_success(tick_duration_s=tick_dur),
                )
            except ProcessingTickFailure as failure:
                decision = self._failure_policy.plan_failure(
                    failure,
                    interval_s=interval,
                )
                delay = await self._apply_failure(decision)
            await anyio.sleep(delay)

    def _apply_success(self, decision: ProcessingSuccessDecision) -> None:
        self.state.last_tick_duration_s = decision.tick_duration_s
        if decision.tick_duration_s > self.state.max_tick_duration_s:
            self.state.max_tick_duration_s = decision.tick_duration_s
        self.state.tick_count += 1
        self.state.processing_state = ProcessingHealth.OK

    async def _apply_failure(self, decision: ProcessingFailureDecision) -> float:
        self.state.processing_failure_count += 1
        self.state.last_failure_category = decision.failure_category
        self.state.last_failure_message = decision.failure_message
        self.state.processing_failure_categories[decision.failure_category] = (
            self.state.processing_failure_categories.get(decision.failure_category, 0) + 1
        )
        self.state.processing_state = decision.processing_state
        if decision.escalation_failure is not None:
            raise decision.escalation_failure
        if decision.backoff_sleep_s is not None:
            await self._failure_policy.complete_backoff(
                cycle=self._failure_policy.fatal_backoff_cycles,
                total_failure_count=self.state.processing_failure_count,
            )
            if decision.post_backoff_state is not None:
                self.state.processing_state = decision.post_backoff_state
        return decision.next_delay_s
