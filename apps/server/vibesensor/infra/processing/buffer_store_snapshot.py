from __future__ import annotations

import time
from collections.abc import Iterable

from vibesensor.infra.processing.buffer_mutations import ClientBufferMutator
from vibesensor.infra.processing.buffer_registry import ClientBufferRegistry
from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.models import (
    CachedMetricsHit,
    ClientMetrics,
    FloatArray,
    MetricsSnapshot,
    ProcessorConfig,
)
from vibesensor.infra.processing.snapshot_builder import check_cache_hit, compute_snapshot_window
from vibesensor.infra.processing.time_align import analysis_time_range
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange


class BufferStoreSnapshotReader:
    """Own read/query and compute-snapshot operations over shared client buffers."""

    __slots__ = ("_buffer_mutator", "_config", "_registry")

    def __init__(
        self,
        *,
        config: ProcessorConfig,
        registry: ClientBufferRegistry,
        buffer_mutator: ClientBufferMutator,
    ) -> None:
        self._config = config
        self._registry = registry
        self._buffer_mutator = buffer_mutator

    def snapshot_for_compute(
        self,
        client_id: str,
        *,
        sample_rate_hz: int | None = None,
    ) -> CachedMetricsHit | MetricsSnapshot | None:
        with self._registry.locked_client_buffer(client_id) as buf:
            if buf is None or buf.count == 0:
                return None
            if sample_rate_hz is not None and sample_rate_hz > 0:
                self._buffer_mutator.apply_sample_rate_override(
                    buf,
                    sample_rate_hz,
                    resize_buffer=False,
                )
            sr = buf.sample_rate_hz or self._config.sample_rate_hz

            cache_hit = check_cache_hit(
                ingest_generation=buf.ingest_generation,
                compute_generation=buf.compute_generation,
                compute_sample_rate_hz=buf.compute_sample_rate_hz,
                effective_sample_rate_hz=sr,
                latest_metrics=buf.latest_metrics,
            )
            if cache_hit is not None:
                return cache_hit

            window = compute_snapshot_window(
                count=buf.count,
                capacity=buf.capacity,
                sample_rate_hz=sr,
                waveform_seconds=self._config.waveform_seconds,
                fft_n=self._config.fft_n,
            )

            fft_block: FloatArray | None = None
            if window.needs_separate_fft_block:
                fft_block = self._buffer_mutator.copy_latest(buf, self._config.fft_n)
                time_window = fft_block[:, -window.n_time :]
            else:
                time_window = self._buffer_mutator.copy_latest(buf, window.n_time)
                if buf.count >= self._config.fft_n:
                    fft_block = time_window[:, -self._config.fft_n :]
            return MetricsSnapshot(
                client_id=client_id,
                sample_rate_hz=sr,
                ingest_generation=buf.ingest_generation,
                buffer_epoch=buf.buffer_epoch,
                time_window=time_window,
                fft_block=fft_block,
                analysis_time_range=self._analysis_time_range(buf, sample_rate_hz=sr),
            )

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        with self._registry.locked_client_buffer(client_id) as buf:
            if buf is None or buf.count == 0:
                return None
            idx = (buf.write_idx - 1) % buf.capacity
            return (
                float(buf.data[0, idx]),
                float(buf.data[1, idx]),
                float(buf.data[2, idx]),
            )

    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        with self._registry.locked_client_buffer(client_id) as buf:
            if buf is None:
                return None
            rate = int(buf.sample_rate_hz or 0)
            return rate if rate > 0 else None

    def latest_analysis_time_range(self, client_id: str) -> AnalysisTimeRange | None:
        with self._registry.locked_client_buffer(client_id) as buf:
            if buf is None:
                return None
            return buf.latest_analysis_time_range

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        with self._registry.locked_client_buffer(client_id) as buf:
            if buf is None:
                return {}
            return buf.latest_metrics

    def all_latest_metrics(self, client_ids: list[str]) -> dict[str, ClientMetrics]:
        with self._registry.locked_client_buffers(client_ids) as buffers:
            result: dict[str, ClientMetrics] = {}
            for cid in client_ids:
                buf = buffers.get(cid)
                if buf is not None and buf.latest_metrics:
                    result[cid] = buf.latest_metrics
            return result

    def _analysis_time_range(
        self,
        buf: ClientBuffer,
        *,
        sample_rate_hz: int,
    ) -> AnalysisTimeRange | None:
        time_range = analysis_time_range(
            count=buf.count,
            last_ingest_mono_s=buf.last_ingest_mono_s,
            sample_rate_hz=sample_rate_hz,
            waveform_seconds=self._config.waveform_seconds,
            capacity=buf.capacity,
            last_t0_us=buf.last_t0_us,
            samples_since_t0=buf.samples_since_t0,
        )
        if time_range is None:
            return None
        start_s, end_s, synced = time_range
        return AnalysisTimeRange(start_s=start_s, end_s=end_s, synced=synced)

    def clients_with_recent_data(
        self,
        client_ids: Iterable[str],
        *,
        max_age_s: float = 3.0,
    ) -> list[str]:
        now = time.monotonic()
        with self._registry.locked_client_buffers(client_ids) as buffers:
            result: list[str] = []
            for client_id in client_ids:
                buf = buffers.get(client_id)
                if buf is None or buf.last_ingest_mono_s <= 0:
                    continue
                if (now - buf.last_ingest_mono_s) <= max_age_s:
                    result.append(client_id)
            return result
