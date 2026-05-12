"""Guard buffer-store cache identity and sample-rate invalidation behavior."""

from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.buffer_capacity import MAX_CLIENT_SAMPLE_RATE_HZ
from vibesensor.infra.processing.buffer_store import SignalBufferStore
from vibesensor.infra.processing.compute import SignalMetricsComputer
from vibesensor.infra.processing.models import MetricsSnapshot, ProcessorConfig


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


def test_snapshot_for_compute_clamps_excessive_sample_rate_override() -> None:
    store = SignalBufferStore(_config())
    client_id = "sensor-1"

    store.ingest(client_id, np.ones((256, 3), dtype=np.float32), sample_rate_hz=200)

    plan = store.snapshot_for_compute(client_id, sample_rate_hz=250_000)

    assert isinstance(plan, MetricsSnapshot)
    assert plan.sample_rate_hz == MAX_CLIENT_SAMPLE_RATE_HZ
    assert store.buffers[client_id].sample_rate_hz == MAX_CLIENT_SAMPLE_RATE_HZ


def test_stale_result_is_rejected_after_buffer_eviction_and_recreation() -> None:
    config = _config()
    store = SignalBufferStore(config)
    computer = SignalMetricsComputer(config)
    client_id = "sensor-2"

    old_samples = np.random.default_rng(0).standard_normal((256, 3)).astype(np.float32)
    new_samples = (np.random.default_rng(1).standard_normal((256, 3)) * 10.0).astype(np.float32)

    store.ingest(client_id, old_samples, sample_rate_hz=200)
    plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)

    assert isinstance(plan, MetricsSnapshot)
    stale_result = computer.compute(plan)

    store.evict_clients(set())
    store.ingest(client_id, new_samples, sample_rate_hz=200)
    recreated_epoch = store.buffers[client_id].buffer_epoch

    assert recreated_epoch != stale_result.buffer_epoch

    store.store_metrics_result(stale_result)

    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        assert buf.latest_metrics == {}

    next_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(next_plan, MetricsSnapshot)
    assert next_plan.buffer_epoch == recreated_epoch


def test_sample_rate_change_forces_fresh_snapshot_before_reusing_cache() -> None:
    config = _config()
    store = SignalBufferStore(config)
    computer = SignalMetricsComputer(config)
    client_id = "sensor-3"

    samples = np.random.default_rng(2).standard_normal((256, 3)).astype(np.float32)
    store.ingest(client_id, samples, sample_rate_hz=200)

    first_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(first_plan, MetricsSnapshot)
    store.store_metrics_result(computer.compute(first_plan))

    changed_rate_plan = store.snapshot_for_compute(client_id, sample_rate_hz=400)
    assert isinstance(changed_rate_plan, MetricsSnapshot)
    assert changed_rate_plan.sample_rate_hz == 400

    changed_result = computer.compute(changed_rate_plan)
    store.store_metrics_result(changed_result)

    assert store.latest_metrics(client_id) == changed_result.metrics
