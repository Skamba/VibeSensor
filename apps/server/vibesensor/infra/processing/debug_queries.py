"""Read-only debug/raw buffer queries extracted from ``SignalBufferStore``."""

from __future__ import annotations

from vibesensor.infra.processing.buffer_store import SignalBufferStore
from vibesensor.infra.processing.models import DebugSpectrumRequest
from vibesensor.shared.types.payload_types import RawSamplesErrorPayload, RawSamplesPayload

__all__ = ["DebugQueryReader"]


class DebugQueryReader:
    """Own debug/raw read queries against locked processing buffers."""

    def __init__(self, store: SignalBufferStore) -> None:
        self._store = store

    def debug_request(self, client_id: str) -> DebugSpectrumRequest:
        with self._store.locked_client_buffer(client_id) as buf:
            if buf is None:
                return DebugSpectrumRequest(
                    client_id=client_id,
                    sample_rate_hz=self._store.config.sample_rate_hz,
                    count=0,
                    fft_block=None,
                )
            sample_rate_hz = buf.sample_rate_hz or self._store.config.sample_rate_hz
            if buf.count < self._store.config.fft_n:
                return DebugSpectrumRequest(
                    client_id=client_id,
                    sample_rate_hz=sample_rate_hz,
                    count=buf.count,
                    fft_block=None,
                )
            return DebugSpectrumRequest(
                client_id=client_id,
                sample_rate_hz=sample_rate_hz,
                count=buf.count,
                fft_block=self._store._buffer_mutator.copy_latest(
                    buf,
                    self._store.config.fft_n,
                ),
            )

    def raw_samples(
        self,
        client_id: str,
        *,
        n_samples: int,
    ) -> RawSamplesPayload | RawSamplesErrorPayload:
        with self._store.locked_client_buffer(client_id) as buf:
            if buf is None or buf.count == 0:
                return {"error": "no data", "count": 0}
            sample_rate_hz = buf.sample_rate_hz or self._store.config.sample_rate_hz
            count = min(n_samples, buf.count)
            block = self._store._buffer_mutator.copy_latest(buf, count)
        return {
            "client_id": client_id,
            "sample_rate_hz": sample_rate_hz,
            "n_samples": count,
            "x": [float(value) for value in block[0].tolist()],
            "y": [float(value) for value in block[1].tolist()],
            "z": [float(value) for value in block[2].tolist()],
        }
