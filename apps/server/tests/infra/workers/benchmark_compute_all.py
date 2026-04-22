"""Explicit pytest-benchmark suite for SignalProcessor compute_all hot path."""

from __future__ import annotations

from math import pi

import numpy as np
import pytest

from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.workers.worker_pool import WorkerPool

SAMPLE_RATE_HZ = 800
WAVEFORM_SECONDS = 4
SPECTRUM_MAX_HZ = 200
INGEST_BATCHES = 5
CLIENT_IDS = [f"sensor-{idx:02d}" for idx in range(4)]
FREQS_HZ = [20.0 + idx * 7.5 for idx in range(len(CLIENT_IDS))]


def _make_processor(
    *,
    fft_n: int,
    pool: WorkerPool | None = None,
) -> SignalProcessor:
    return SignalProcessor(
        sample_rate_hz=SAMPLE_RATE_HZ,
        waveform_seconds=WAVEFORM_SECONDS,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_max_hz=SPECTRUM_MAX_HZ,
        accel_scale_g_per_lsb=1.0 / 256.0,
        worker_pool=pool,
    )


def _inject_signal(proc: SignalProcessor, client_id: str, freq_hz: float, *, fft_n: int) -> None:
    t = np.arange(fft_n, dtype=np.float64) / SAMPLE_RATE_HZ
    x_lsb = (0.05 * np.sin(2.0 * pi * freq_hz * t) * 256.0).astype(np.int16)
    y_lsb = (0.03 * np.sin(2.0 * pi * (freq_hz + 10.0) * t) * 256.0).astype(np.int16)
    z_lsb = np.zeros(fft_n, dtype=np.int16)
    samples = np.stack([x_lsb, y_lsb, z_lsb], axis=1)
    proc.ingest(client_id, samples, sample_rate_hz=SAMPLE_RATE_HZ)


def _run_compute_round(
    use_worker_pool: bool,
    *,
    fft_n: int,
) -> tuple[dict[str, object], int | None]:
    pool = WorkerPool(max_workers=4, thread_name_prefix="bench-fft") if use_worker_pool else None
    try:
        proc = _make_processor(fft_n=fft_n, pool=pool)
        for client_id, freq_hz in zip(CLIENT_IDS, FREQS_HZ, strict=True):
            for _ in range(INGEST_BATCHES):
                _inject_signal(proc, client_id, freq_hz, fft_n=fft_n)
        result = proc.compute_all(CLIENT_IDS)
        worker_pool_tasks = None
        if pool is not None:
            worker_pool_tasks = proc.intake_stats()["worker_pool"]["total_tasks"]
        return result, worker_pool_tasks
    finally:
        if pool is not None:
            pool.shutdown()


@pytest.mark.benchmark(group="signal-processor-compute-round")
@pytest.mark.parametrize("fft_n", [512, 2048], ids=["fft-512", "fft-2048"])
@pytest.mark.parametrize("use_worker_pool", [False, True], ids=["sequential", "parallel"])
def test_signal_processor_compute_round_benchmark(
    benchmark,
    use_worker_pool: bool,
    fft_n: int,
) -> None:
    result, worker_pool_tasks = benchmark(lambda: _run_compute_round(use_worker_pool, fft_n=fft_n))

    assert sorted(result) == CLIENT_IDS
    assert result["sensor-00"]["x"]["rms"] > 0
    assert result["sensor-01"]["y"]["rms"] > 0
    if not use_worker_pool:
        assert worker_pool_tasks is None
    elif fft_n == 512:
        assert worker_pool_tasks == 0
    else:
        assert worker_pool_tasks == len(CLIENT_IDS)
