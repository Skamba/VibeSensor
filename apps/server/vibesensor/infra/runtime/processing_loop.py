"""Runtime processing loop: observable state, tick execution, and failure policy.

- ``ProcessingLoopState`` / ``ProcessingHealth``: health and timing state read by
  health reporting.
- ``ProcessingTickFailure`` / ``ProcessingFailureCategory``: typed per-tick
  operational failures.
- ``ProcessingFailurePolicy``: retry/backoff/escalation decisions.
- ``ProcessingTickRunner``: one tick (clock sync, compute, evict).
- ``ProcessingLoop``: async tick scheduling over the runner and the policy.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING

import anyio

from vibesensor.shared.exceptions import ProcessingError
from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.ports import ClockSyncBroadcaster
from vibesensor.shared.runtime_failures import ProcessingLoopFailure

if TYPE_CHECKING:
    from vibesensor.infra.processing.processor import SignalProcessor
    from vibesensor.ingest.registry import ClientRegistry

LOGGER = logging.getLogger(__name__)

STALE_DATA_AGE_S = 2.0
"""Clients without fresh UDP data within this window are excluded from spectrum output."""

MAX_CONSECUTIVE_FAILURES = 25
"""After this many consecutive processing failures, enter fatal backoff."""

FAILURE_BACKOFF_S = 5
"""Seconds to sleep on fatal failure threshold before retrying the loop."""

MAX_FATAL_BACKOFF_CYCLES = 3
"""After this many fatal backoff cycles, escalate to a managed task failure."""

_MAX_FAILURE_MESSAGE_LEN = 240
_MAX_RETRY_DELAY_S = 5.0
_MAX_BACKOFF_EXPONENT = 6

_OPERATIONAL_PROCESSING_EXCEPTIONS = (OSError, ProcessingError)
_LOW_LOAD_FAST_PATH_CLIENT_LIMIT = 8
_LOW_LOAD_FAST_PATH_UPDATE_HZ = 10
_LOW_LOAD_MAX_DUTY_CYCLE = 0.5


class ProcessingHealth(StrEnum):
    """Health status of the processing loop."""

    OK = "ok"
    DEGRADED = "degraded"
    FATAL = "fatal"


@dataclass(slots=True)
class ProcessingLoopState:
    """Mutable health and timing state for the runtime processing loop."""

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


class ProcessingFailureCategory(StrEnum):
    """Stable categories for operational processing-tick failures."""

    SYNC_CLOCK = "sync_clock"
    COMPUTE_ALL = "compute_all"
    EVICT_CLIENTS = "evict_clients"


class ProcessingTickFailure(ProcessingError):
    """Categorized operational processing-tick failure."""

    def __init__(self, category: ProcessingFailureCategory, cause: Exception) -> None:
        super().__init__(str(cause))
        self.category = category
        self.cause = cause


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


class ProcessingTickRunner:
    """Run one processing tick against the registry and processor dependencies."""

    __slots__ = (
        "_control_plane",
        "_fft_n",
        "_processor",
        "_registry",
        "_sample_rate_hz",
        "_state",
    )

    def __init__(
        self,
        *,
        state: ProcessingLoopState,
        sample_rate_hz: int,
        fft_n: int,
        registry: ClientRegistry,
        processor: SignalProcessor,
        control_plane: ClockSyncBroadcaster | None = None,
    ) -> None:
        self._state = state
        self._sample_rate_hz = sample_rate_hz
        self._fft_n = fft_n
        self._registry = registry
        self._processor = processor
        self._control_plane = control_plane

    async def run(self, *, sync_clock: bool) -> int:
        if sync_clock:
            await self._sync_clock()
        compute_client_ids, sample_rates = self._collect_compute_clients()
        await self._compute_and_evict_clients(
            compute_client_ids=compute_client_ids,
            sample_rates=sample_rates,
        )
        return len(compute_client_ids)

    async def _sync_clock(self) -> None:
        if self._control_plane is None:
            return
        try:
            await anyio.to_thread.run_sync(self._control_plane.broadcast_sync_clock)
        except OSError as exc:
            raise ProcessingTickFailure(ProcessingFailureCategory.SYNC_CLOCK, exc) from exc

    def _collect_compute_clients(self) -> tuple[list[str], dict[str, int]]:
        self._registry.evict_stale()
        active_ids = self._registry.active_client_ids()
        fresh_ids = self._processor.clients_with_recent_data(
            active_ids,
            max_age_s=STALE_DATA_AGE_S,
        )

        sample_rates: dict[str, int] = {}
        compute_client_ids: list[str] = []
        for client_id in fresh_ids:
            record = self._registry.get(client_id)
            if record is None:
                continue
            compute_client_ids.append(client_id)
            sample_rates[client_id] = record.sample_rate_hz
            self._log_sample_rate_mismatch(client_id, int(record.sample_rate_hz or 0))
            self._log_frame_size_mismatch(client_id, int(record.frame_samples or 0))
        return compute_client_ids, sample_rates

    def _log_sample_rate_mismatch(self, client_id: str, client_rate: int) -> None:
        if (
            client_rate <= 0
            or client_rate == self._sample_rate_hz
            or client_id in self._state.sample_rate_mismatch_logged
        ):
            return
        self._state.sample_rate_mismatch_logged.add(client_id)
        LOGGER.warning(
            "Client %s uses sample_rate_hz=%d; default config is %d.",
            client_id,
            client_rate,
            self._sample_rate_hz,
        )

    def _log_frame_size_mismatch(self, client_id: str, frame_samples: int) -> None:
        if (
            frame_samples <= 0
            or frame_samples <= self._fft_n
            or client_id in self._state.frame_size_mismatch_logged
        ):
            return
        self._state.frame_size_mismatch_logged.add(client_id)
        LOGGER.error(
            "Client %s reported frame_samples=%d larger than fft_n=%d; ingest may be degraded.",
            client_id,
            frame_samples,
            self._fft_n,
        )

    async def _compute_and_evict_clients(
        self,
        *,
        compute_client_ids: list[str],
        sample_rates: dict[str, int],
    ) -> None:
        compute_failure: ProcessingTickFailure | None = None
        try:
            await anyio.to_thread.run_sync(
                partial(
                    self._processor.compute_all,
                    compute_client_ids,
                    sample_rates_hz=sample_rates,
                )
            )
        except _OPERATIONAL_PROCESSING_EXCEPTIONS as exc:
            compute_failure = ProcessingTickFailure(
                ProcessingFailureCategory.COMPUTE_ALL,
                exc,
            )

        try:
            self._processor.evict_clients(set(self._registry.active_client_ids()))
        except _OPERATIONAL_PROCESSING_EXCEPTIONS as exc:
            if compute_failure is not None:
                LOGGER.warning(
                    "Processing loop cleanup also failed after compute_all failure; "
                    "reporting compute_all as the primary error.",
                    exc_info=True,
                )
                raise compute_failure from compute_failure.cause
            raise ProcessingTickFailure(ProcessingFailureCategory.EVICT_CLIENTS, exc) from exc

        if compute_failure is not None:
            raise compute_failure from compute_failure.cause


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

    async def _run_tick(self, *, sync_clock: bool) -> int:
        return await self._tick_runner.run(sync_clock=sync_clock)

    def _success_delay_s(
        self,
        *,
        interval_s: float,
        tick_duration_s: float,
        active_client_count: int,
    ) -> float:
        if active_client_count <= 0:
            return interval_s
        if active_client_count > _LOW_LOAD_FAST_PATH_CLIENT_LIMIT:
            return interval_s

        fast_path_period_s = 1.0 / _LOW_LOAD_FAST_PATH_UPDATE_HZ
        duty_cycle_period_s = tick_duration_s / _LOW_LOAD_MAX_DUTY_CYCLE
        target_period_s = max(fast_path_period_s, duty_cycle_period_s)
        return max(0.0, target_period_s - tick_duration_s)

    async def run(self) -> None:
        """Tick loop: low-load fast path with bounded CPU, default cadence otherwise."""
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
                active_client_count = await self._run_tick(sync_clock=sync_clock)
                tick_dur = time.monotonic() - tick_start
                delay = self._success_delay_s(
                    interval_s=interval,
                    tick_duration_s=tick_dur,
                    active_client_count=active_client_count,
                )
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
