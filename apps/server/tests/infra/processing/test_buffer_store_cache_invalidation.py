"""Verify buffer-store mutations invalidate cached spectrum payload state."""

from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.buffer_store import SignalBufferStore
from vibesensor.infra.processing.models import (
    MetricsComputationResult,
    MetricsSnapshot,
    ProcessorConfig,
)


def _config(**overrides: object) -> ProcessorConfig:
    base = {
        "sample_rate_hz": 200,
        "waveform_seconds": 2,
        "waveform_display_hz": 50,
        "fft_n": 128,
        "spectrum_min_hz": 0.0,
        "spectrum_max_hz": 100.0,
        "accel_scale_g_per_lsb": None,
    }
    base.update(overrides)
    return ProcessorConfig(**base)


def _seed_cached_payload(store: SignalBufferStore, client_id: str) -> None:
    with store.locked_client_buffer(client_id, create=True) as buf:
        assert buf is not None
        buf.cached_spectrum_payload = {"freq": [1.0, 2.0]}


def test_ingest_and_flush_invalidate_cached_payloads() -> None:
    store = SignalBufferStore(_config())
    client_id = "sensor-cache"

    store.ingest(client_id, np.ones((16, 3), dtype=np.float32), sample_rate_hz=200)
    _seed_cached_payload(store, client_id)

    store.ingest(client_id, np.full((8, 3), 2.0, dtype=np.float32), sample_rate_hz=200)

    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        assert buf.cached_spectrum_payload is None

    _seed_cached_payload(store, client_id)
    store.flush_client_buffer(client_id)

    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        assert buf.cached_spectrum_payload is None


def test_store_metrics_result_invalidates_cached_payloads() -> None:
    store = SignalBufferStore(_config())
    client_id = "sensor-store"

    store.ingest(client_id, np.ones((256, 3), dtype=np.float32), sample_rate_hz=200)
    _seed_cached_payload(store, client_id)

    plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(plan, MetricsSnapshot)

    store.store_metrics_result(
        MetricsComputationResult(
            client_id=client_id,
            sample_rate_hz=plan.sample_rate_hz,
            ingest_generation=plan.ingest_generation,
            metrics={"combined": {"vib_mag_rms": 1.0, "vib_mag_p2p": 2.0, "peaks": []}},
            spectrum_by_axis={},
            strength_metrics={},
            has_fft_data=False,
            duration_s=0.01,
            buffer_epoch=plan.buffer_epoch,
        )
    )

    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        assert buf.cached_spectrum_payload is None
