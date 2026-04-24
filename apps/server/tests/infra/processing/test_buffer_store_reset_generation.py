from __future__ import annotations

import numpy as np

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


def test_flush_rejects_pre_reset_inflight_result() -> None:
    config = _config()
    store = SignalBufferStore(config)
    computer = SignalMetricsComputer(config)
    client_id = "sensor-reset-stale"

    samples = np.random.default_rng(0).standard_normal((256, 3)).astype(np.float32)
    store.ingest(client_id, samples, sample_rate_hz=200)
    stale_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)

    assert isinstance(stale_plan, MetricsSnapshot)
    stale_result = computer.compute(stale_plan)

    store.flush_client_buffer(client_id)
    store.store_metrics_result(stale_result)

    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        assert buf.count == 0
        assert buf.latest_metrics == {}
        assert buf.compute_generation == -1
        assert buf.reset_generation == stale_plan.reset_generation + 1


def test_post_reset_result_commits_after_new_ingest() -> None:
    config = _config()
    store = SignalBufferStore(config)
    computer = SignalMetricsComputer(config)
    client_id = "sensor-reset-fresh"

    old_samples = np.random.default_rng(1).standard_normal((256, 3)).astype(np.float32)
    new_samples = (np.random.default_rng(2).standard_normal((256, 3)) * 5.0).astype(np.float32)

    store.ingest(client_id, old_samples, sample_rate_hz=200)
    stale_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(stale_plan, MetricsSnapshot)
    stale_result = computer.compute(stale_plan)

    store.flush_client_buffer(client_id)
    store.ingest(client_id, new_samples, sample_rate_hz=200)
    fresh_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(fresh_plan, MetricsSnapshot)
    fresh_result = computer.compute(fresh_plan)

    store.store_metrics_result(stale_result)
    store.store_metrics_result(fresh_result)

    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        assert buf.reset_generation == fresh_plan.reset_generation
        assert buf.compute_generation == fresh_result.ingest_generation
        assert buf.latest_metrics == fresh_result.metrics


def test_repeated_resets_keep_older_results_rejected() -> None:
    config = _config()
    store = SignalBufferStore(config)
    computer = SignalMetricsComputer(config)
    client_id = "sensor-reset-repeat"

    first_samples = np.random.default_rng(3).standard_normal((256, 3)).astype(np.float32)
    second_samples = np.random.default_rng(4).standard_normal((256, 3)).astype(np.float32)

    store.ingest(client_id, first_samples, sample_rate_hz=200)
    first_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(first_plan, MetricsSnapshot)
    first_result = computer.compute(first_plan)

    store.flush_client_buffer(client_id)
    store.ingest(client_id, second_samples, sample_rate_hz=200)
    second_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(second_plan, MetricsSnapshot)
    second_result = computer.compute(second_plan)

    store.flush_client_buffer(client_id)
    store.store_metrics_result(first_result)
    store.store_metrics_result(second_result)

    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        assert buf.count == 0
        assert buf.reset_generation == second_plan.reset_generation + 1
        assert buf.latest_metrics == {}
        assert buf.compute_generation == -1
