"""ProcessingLoop – async tick loop with failure tracking.

Owns:
- ``ProcessingLoopState`` dataclass (failure counters + mismatch guards)
- The ~100 ms tick coroutine that evicts stale clients and computes metrics
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .subsystems import RuntimeIngressSubsystem

LOGGER = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 25
"""After this many consecutive processing failures, enter fatal backoff."""

FAILURE_BACKOFF_S = 30
"""Seconds to sleep on fatal failure threshold before resetting."""

STALE_DATA_AGE_S = 2.0
"""Clients without fresh UDP data within this window are excluded from spectrum output."""

_COMPUTE_TIMEOUT_S: float = 10.0
"""Timeout applied to the asyncio.to_thread() call for compute_all().

Prevents a stalled FFT computation from blocking the event loop indefinitely.
Matches the DB-thread timeout used in MetricsLogger (_DB_THREAD_TIMEOUT_S) for
consistency.  The timed-out thread continues running in the background (Python
threads cannot be forcibly killed), but the event loop is freed immediately.
"""

_MAX_FAILURE_MESSAGE_LEN = 240


class ProcessingLoopError(RuntimeError):
    """Categorized processing-loop failure with a stable health-reporting key."""

    def __init__(self, category: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.category = category
        self.cause = cause


@dataclass(slots=True)
class ProcessingLoopState:
    """Mutable tracking state for the processing loop.

    Failure counters and mismatch log-guards form a coherent,
    narrowly-scoped unit.
    """

    processing_state: str = "ok"
    processing_failure_count: int = 0
    processing_failure_categories: dict[str, int] = field(default_factory=dict)
    last_failure_category: str | None = None
    last_failure_message: str | None = None
    sample_rate_mismatch_logged: set[str] = field(default_factory=set)
    frame_size_mismatch_logged: set[str] = field(default_factory=set)


class ProcessingLoop:
    """Async processing tick loop: evict stale clients, compute metrics, handle failures."""

    __slots__ = (
        "state",
        "_fft_update_hz",
        "_sample_rate_hz",
        "_fft_n",
        "_ingress",
    )

    def __init__(
        self,
        *,
        state: ProcessingLoopState,
        fft_update_hz: int,
        sample_rate_hz: int,
        fft_n: int,
        ingress: RuntimeIngressSubsystem,
    ) -> None:
        self.state = state
        self._fft_update_hz = fft_update_hz
        self._sample_rate_hz = sample_rate_hz
        self._fft_n = fft_n
        self._ingress = ingress

    @staticmethod
    def _truncate_failure_message(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        if len(message) > _MAX_FAILURE_MESSAGE_LEN:
            return f"{message[: _MAX_FAILURE_MESSAGE_LEN - 1]}..."
        return message

    def _record_failure(self, category: str, exc: Exception) -> None:
        state = self.state
        state.processing_failure_count += 1
        state.last_failure_category = category
        state.last_failure_message = self._truncate_failure_message(exc)
        state.processing_failure_categories[category] = (
            state.processing_failure_categories.get(category, 0) + 1
        )

    async def _run_tick(self, *, sync_clock: bool) -> None:
        if sync_clock:
            try:
                self._ingress.control_plane.broadcast_sync_clock()
            except Exception as exc:
                raise ProcessingLoopError("sync_clock", exc) from exc

        try:
            self._ingress.registry.evict_stale()
            active_ids = self._ingress.registry.active_client_ids()
            fresh_ids = self._ingress.processor.clients_with_recent_data(
                active_ids, max_age_s=STALE_DATA_AGE_S
            )
        except Exception as exc:
            raise ProcessingLoopError("ingress_state", exc) from exc

        sample_rates: dict[str, int] = {}
        state = self.state
        for client_id in fresh_ids:
            try:
                record = self._ingress.registry.get(client_id)
            except Exception as exc:
                raise ProcessingLoopError("registry_lookup", exc) from exc
            if record is None:
                continue
            sample_rates[client_id] = record.sample_rate_hz
            client_rate = int(record.sample_rate_hz or 0)
            if (
                client_rate > 0
                and client_rate != self._sample_rate_hz
                and client_id not in state.sample_rate_mismatch_logged
            ):
                state.sample_rate_mismatch_logged.add(client_id)
                LOGGER.warning(
                    "Client %s uses sample_rate_hz=%d; default config is %d.",
                    client_id,
                    client_rate,
                    self._sample_rate_hz,
                )
            frame_samples = int(record.frame_samples or 0)
            if (
                frame_samples > 0
                and frame_samples > self._fft_n
                and client_id not in state.frame_size_mismatch_logged
            ):
                state.frame_size_mismatch_logged.add(client_id)
                LOGGER.error(
                    "Client %s reported frame_samples=%d larger than fft_n=%d; "
                    "ingest may be degraded.",
                    client_id,
                    frame_samples,
                    self._fft_n,
                )

        try:
            metrics_by_client = await asyncio.wait_for(
                asyncio.to_thread(
                    self._ingress.processor.compute_all,
                    fresh_ids,
                    sample_rates_hz=sample_rates,
                ),
                timeout=_COMPUTE_TIMEOUT_S,
            )
        except TimeoutError as exc:
            raise ProcessingLoopError("compute_all_timeout", exc) from exc
        except Exception as exc:
            raise ProcessingLoopError("compute_all", exc) from exc

        try:
            for client_id, metrics in metrics_by_client.items():
                self._ingress.registry.set_latest_metrics(client_id, metrics)
            self._ingress.processor.evict_clients(set(active_ids))
        except Exception as exc:
            raise ProcessingLoopError("publish_metrics", exc) from exc

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
                await self._run_tick(sync_clock=sync_clock)
                consecutive_failures = 0
                self.state.processing_state = "ok"
            except ProcessingLoopError as exc:
                consecutive_failures += 1
                self._record_failure(exc.category, exc.cause)
                is_fatal = consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                self.state.processing_state = "fatal" if is_fatal else "degraded"
                LOGGER.warning(
                    "Processing loop tick failed in %s; will retry.",
                    exc.category,
                    exc_info=True,
                )
                if is_fatal:
                    LOGGER.error(
                        "Processing loop hit %d failures; backing off %d s then resetting",
                        MAX_CONSECUTIVE_FAILURES,
                        FAILURE_BACKOFF_S,
                    )
                    await asyncio.sleep(FAILURE_BACKOFF_S)
                    consecutive_failures = 0
                    self.state.processing_state = "degraded"
                    LOGGER.info(
                        "Processing loop resuming after fatal-backoff; "
                        "total failure count so far: %d",
                        self.state.processing_failure_count,
                    )
            except Exception as exc:
                consecutive_failures += 1
                self._record_failure("unexpected", exc)
                is_fatal = consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                self.state.processing_state = "fatal" if is_fatal else "degraded"
                LOGGER.warning(
                    "Processing loop tick failed unexpectedly; will retry.",
                    exc_info=True,
                )
                if is_fatal:
                    LOGGER.error(
                        "Processing loop hit %d failures; backing off %d s then resetting",
                        MAX_CONSECUTIVE_FAILURES,
                        FAILURE_BACKOFF_S,
                    )
                    await asyncio.sleep(FAILURE_BACKOFF_S)
                    consecutive_failures = 0
                    self.state.processing_state = "degraded"
                    LOGGER.info(
                        "Processing loop resuming after fatal-backoff; "
                        "total failure count so far: %d",
                        self.state.processing_failure_count,
                    )
            delay = (
                interval
                if consecutive_failures == 0
                else min(5.0, interval * (2 ** min(6, consecutive_failures)))
            )
            await asyncio.sleep(delay)
