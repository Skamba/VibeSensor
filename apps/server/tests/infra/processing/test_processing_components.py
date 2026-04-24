"""Cover snapshot, cache, and FFT-parameter behavior across processing components."""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.infra.processing.buffer_store import SignalBufferStore
from vibesensor.infra.processing.compute import SignalMetricsComputer
from vibesensor.infra.processing.models import (
    CachedMetricsHit,
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


def test_buffer_store_returns_cached_hit_after_committed_generation() -> None:
    config = _config()
    store = SignalBufferStore(config)
    client_id = "client-1"
    samples = np.random.default_rng(1).standard_normal((256, 3)).astype(np.float32)

    store.ingest(client_id, samples, sample_rate_hz=200)
    first_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(first_plan, MetricsSnapshot)

    store.store_metrics_result(
        MetricsComputationResult(
            client_id=client_id,
            sample_rate_hz=200,
            ingest_generation=first_plan.ingest_generation,
            metrics={"combined": {"vib_mag_rms": 1.0, "vib_mag_p2p": 2.0, "peaks": []}},
            spectrum_by_axis={},
            strength_metrics={},
            has_fft_data=False,
            duration_s=0.01,
        ),
    )

    second_plan = store.snapshot_for_compute(client_id, sample_rate_hz=200)
    assert isinstance(second_plan, CachedMetricsHit)
    assert second_plan.metrics["combined"]["vib_mag_rms"] == 1.0


def test_metrics_computer_operates_on_snapshot_without_shared_state() -> None:
    config = _config(sample_rate_hz=400, fft_n=256, spectrum_max_hz=150.0)
    computer = SignalMetricsComputer(config)
    t = np.arange(config.fft_n, dtype=np.float32) / np.float32(config.sample_rate_hz)
    tone = (0.05 * np.sin(2.0 * np.pi * 20.0 * t)).astype(np.float32)
    block = np.stack([tone, np.zeros_like(tone), np.zeros_like(tone)], axis=0)
    snapshot = MetricsSnapshot(
        client_id="client-2",
        sample_rate_hz=config.sample_rate_hz,
        ingest_generation=7,
        time_window=block.copy(),
        fft_block=block.copy(),
    )

    result = computer.compute(snapshot)

    assert result.client_id == "client-2"
    assert result.ingest_generation == 7
    assert result.metrics["x"]["rms"] > 0
    assert any(abs(float(peak["hz"]) - 20.0) < 1.0 for peak in result.metrics["combined"]["peaks"])


def test_buffer_store_reuses_fft_snapshot_for_short_time_window() -> None:
    store = SignalBufferStore(_config(sample_rate_hz=8, waveform_seconds=1, fft_n=4))
    client_id = "client-short-window"

    store.ingest(
        client_id,
        np.arange(12, dtype=np.float32).reshape(4, 3),
        sample_rate_hz=8,
    )

    plan = store.snapshot_for_compute(client_id, sample_rate_hz=2)

    assert isinstance(plan, MetricsSnapshot)
    assert plan.fft_block is not None
    assert plan.time_window.shape == (3, 2)
    assert plan.fft_block.shape == (3, 4)
    assert np.shares_memory(plan.time_window, plan.fft_block)
    np.testing.assert_array_equal(plan.time_window, plan.fft_block[:, -2:])


def test_buffer_store_does_not_regress_last_t0_us_for_older_frame() -> None:
    store = SignalBufferStore(_config())
    client_id = "client-1"

    store.ingest(
        client_id,
        np.ones((4, 3), dtype=np.float32),
        sample_rate_hz=200,
        t0_us=1_000_000,
    )
    store.ingest(
        client_id,
        np.ones((2, 3), dtype=np.float32),
        sample_rate_hz=200,
        t0_us=900_000,
    )

    with store.lock:
        buf = store.buffers[client_id]
        assert buf.last_t0_us == 1_000_000
        assert buf.samples_since_t0 == 6


def test_buffer_store_warns_and_truncates_oversized_ingest(caplog) -> None:
    store = SignalBufferStore(_config(sample_rate_hz=4, waveform_seconds=1))
    client_id = "client-oversized"
    samples = np.arange(18, dtype=np.float32).reshape(6, 3)

    with caplog.at_level("WARNING", logger="vibesensor.infra.processing.buffer_store"):
        store.ingest(client_id, samples, sample_rate_hz=4)

    assert "exceeds buffer capacity 4" in caplog.text
    assert "discarding 2 oldest samples" in caplog.text
    assert store.buffer_overflow_drops() == 2
    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        latest = store._buffer_mutator.copy_latest(buf, 4).T
    np.testing.assert_array_equal(latest, samples[-4:])


def test_buffer_store_adjusts_t0_us_for_oversized_ingest() -> None:
    store = SignalBufferStore(_config(sample_rate_hz=4, waveform_seconds=1))
    client_id = "client-oversized-t0"
    samples = np.arange(18, dtype=np.float32).reshape(6, 3)

    store.ingest(client_id, samples, sample_rate_hz=4, t0_us=1_000_000)

    with store.locked_client_buffer(client_id) as buf:
        assert buf is not None
        assert buf.last_t0_us == 1_500_000
        assert buf.samples_since_t0 == 4
    plan = store.snapshot_for_compute(client_id, sample_rate_hz=4)
    assert isinstance(plan, MetricsSnapshot)
    assert plan.analysis_time_range is not None
    assert plan.analysis_time_range.start_s == pytest.approx(1.5)
    assert plan.analysis_time_range.end_s == pytest.approx(2.5)


def test_fft_params_uses_lru_eviction(monkeypatch) -> None:
    monkeypatch.setattr("vibesensor.shared.fft_analysis._FFT_CACHE_MAXSIZE", 2)
    computer = SignalMetricsComputer(_config(fft_n=8, sample_rate_hz=200, spectrum_max_hz=90.0))

    computer.fft_params(200)
    computer.fft_params(300)
    computer.fft_params(200)
    computer.fft_params(400)

    assert list(computer.fft_cache) == [200, 400]
