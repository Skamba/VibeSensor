"""ProcessingLoop – async tick scheduling over tick execution and failure policy."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from vibesensor.shared.ports import ClockSyncBroadcaster

from .processing_failure_policy import ProcessingFailurePolicy
from .processing_failures import ProcessingTickFailure
from .processing_state import ProcessingLoopState
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
                self._failure_policy.record_success(self.state, tick_duration_s=tick_dur)
            except ProcessingTickFailure as failure:
                delay = await self._failure_policy.record_failure(
                    self.state,
                    failure,
                    interval_s=interval,
                )
            await asyncio.sleep(delay)
