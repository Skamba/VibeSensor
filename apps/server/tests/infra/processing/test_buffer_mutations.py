from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.buffer_mutations import ClientBufferMutator
from vibesensor.infra.processing.buffer_registry import ClientBufferRegistry
from vibesensor.infra.processing.models import MetricsComputationResult, ProcessorConfig


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


def test_reset_clears_cached_payloads_and_bumps_generation() -> None:
    registry = ClientBufferRegistry(_config())
    mutator = ClientBufferMutator(_config())
    with registry.lock:
        buf = registry._get_or_create_unlocked("sensor-reset")
    buf.data[:] = 1.0
    buf.count = 8
    buf.reset_generation = 2
    buf.ingest_generation = 4
    buf.compute_generation = 3
    buf.compute_sample_rate_hz = 200
    buf.cached_spectrum_payload = {"freq": [1.0, 2.0]}
    buf.cached_spectrum_payload_generation = 9

    mutator.reset(buf)

    assert buf.count == 0
    assert buf.write_idx == 0
    assert buf.reset_generation == 3
    assert buf.ingest_generation == 5
    assert buf.compute_generation == -1
    assert buf.compute_sample_rate_hz == 0
    assert buf.cached_spectrum_payload is None
    assert buf.cached_spectrum_payload_generation == -1
    np.testing.assert_array_equal(buf.data, np.zeros_like(buf.data))


def test_commit_metrics_result_rejects_stale_buffer_epoch() -> None:
    registry = ClientBufferRegistry(_config())
    mutator = ClientBufferMutator(_config())
    with registry.lock:
        buf = registry._get_or_create_unlocked("sensor-stale")
    buf.latest_metrics = {"combined": {"vib_mag_rms": 0.5, "vib_mag_p2p": 1.0, "peaks": []}}

    accepted = mutator.commit_metrics_result(
        buf,
        MetricsComputationResult(
            client_id="sensor-stale",
            sample_rate_hz=200,
            ingest_generation=3,
            metrics={"combined": {"vib_mag_rms": 2.0, "vib_mag_p2p": 4.0, "peaks": []}},
            spectrum_by_axis={},
            strength_metrics={},
            has_fft_data=False,
            duration_s=0.01,
            buffer_epoch=buf.buffer_epoch + 1,
        ),
    )

    assert not accepted
    assert buf.latest_metrics["combined"]["vib_mag_rms"] == 0.5
    assert buf.compute_generation == -1


def test_commit_metrics_result_rejects_stale_reset_generation() -> None:
    registry = ClientBufferRegistry(_config())
    mutator = ClientBufferMutator(_config())
    with registry.lock:
        buf = registry._get_or_create_unlocked("sensor-reset-stale")
    buf.latest_metrics = {"combined": {"vib_mag_rms": 0.5, "vib_mag_p2p": 1.0, "peaks": []}}
    buf.reset_generation = 4

    accepted = mutator.commit_metrics_result(
        buf,
        MetricsComputationResult(
            client_id="sensor-reset-stale",
            sample_rate_hz=200,
            ingest_generation=3,
            metrics={"combined": {"vib_mag_rms": 2.0, "vib_mag_p2p": 4.0, "peaks": []}},
            spectrum_by_axis={},
            strength_metrics={},
            has_fft_data=False,
            duration_s=0.01,
            buffer_epoch=buf.buffer_epoch,
            reset_generation=buf.reset_generation - 1,
        ),
    )

    assert not accepted
    assert buf.latest_metrics["combined"]["vib_mag_rms"] == 0.5
    assert buf.compute_generation == -1
