from __future__ import annotations

import numpy as np

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
