"""Single-tick processing logic for the runtime processing loop."""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Protocol

import anyio

from vibesensor.shared.exceptions import ProcessingError
from vibesensor.shared.ports import ClockSyncBroadcaster

from .processing_failures import ProcessingFailureCategory, ProcessingTickFailure

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry

LOGGER = logging.getLogger(__name__)

_OPERATIONAL_PROCESSING_EXCEPTIONS = (OSError, ProcessingError)

STALE_DATA_AGE_S = 2.0
"""Clients without fresh UDP data within this window are excluded from spectrum output."""


class ProcessingTickState(Protocol):
    sample_rate_mismatch_logged: set[str]
    frame_size_mismatch_logged: set[str]


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
        state: ProcessingTickState,
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

    async def run(self, *, sync_clock: bool) -> None:
        if sync_clock:
            await self._sync_clock()
        compute_client_ids, sample_rates = self._collect_compute_clients()
        await self._compute_and_evict_clients(
            compute_client_ids=compute_client_ids,
            sample_rates=sample_rates,
        )

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
