from __future__ import annotations

from math import pi

import numpy as np

from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.workers.worker_pool import WorkerPool


def _make_processor(*, fft_n: int, pool: WorkerPool) -> SignalProcessor:
    return SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_max_hz=200,
        accel_scale_g_per_lsb=1.0 / 256.0,
        worker_pool=pool,
    )


def _inject_signal(
    proc: SignalProcessor,
    client_id: str,
    *,
    fft_n: int,
    freq_hz: float,
) -> None:
    t = np.arange(fft_n, dtype=np.float64) / 800
    x_lsb = (0.05 * np.sin(2.0 * pi * freq_hz * t) * 256.0).astype(np.int16)
    y_lsb = (0.03 * np.sin(2.0 * pi * (freq_hz + 10.0) * t) * 256.0).astype(np.int16)
    z_lsb = np.zeros(fft_n, dtype=np.int16)
    samples = np.stack([x_lsb, y_lsb, z_lsb], axis=1)
    proc.ingest(client_id, samples, sample_rate_hz=800)


def test_compute_all_small_workload_skips_worker_pool() -> None:
    client_ids = [f"sensor-{idx:02d}" for idx in range(4)]
    with WorkerPool(max_workers=4, thread_name_prefix="test-cutoff-small") as pool:
        proc = _make_processor(fft_n=512, pool=pool)
        for client_id, freq_hz in zip(client_ids, [20.0, 27.5, 35.0, 42.5], strict=True):
            _inject_signal(proc, client_id, fft_n=512, freq_hz=freq_hz)

        result = proc.compute_all(client_ids)

        assert sorted(result) == client_ids
        assert result["sensor-00"]["x"]["rms"] > 0
        assert proc.intake_stats()["worker_pool"]["total_tasks"] == 0


def test_compute_all_threshold_workload_uses_worker_pool() -> None:
    client_ids = ["sensor-00", "sensor-01"]
    with WorkerPool(max_workers=4, thread_name_prefix="test-cutoff-threshold") as pool:
        proc = _make_processor(fft_n=2048, pool=pool)
        for client_id, freq_hz in zip(client_ids, [20.0, 27.5], strict=True):
            _inject_signal(proc, client_id, fft_n=2048, freq_hz=freq_hz)

        result = proc.compute_all(client_ids)

        assert sorted(result) == client_ids
        assert result["sensor-00"]["x"]["rms"] > 0
        assert proc.intake_stats()["worker_pool"]["total_tasks"] == 2
