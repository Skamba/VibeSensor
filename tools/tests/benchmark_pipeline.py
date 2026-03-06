#!/usr/bin/env python3
"""Multi-sensor throughput benchmark for VibeSensor pipeline.

Measures ingest and compute latency with and without the parallel worker pool
to quantify the improvement from multithreaded FFT.

Usage::

    python tools/tests/benchmark_pipeline.py
    python tools/tests/benchmark_pipeline.py --sensors 8 --rounds 20

Output is a plain-text table comparing sequential vs parallel execution.
"""

from __future__ import annotations

import argparse
import statistics
import time
from math import pi

import numpy as np

from vibesensor.processing import SignalProcessor
from vibesensor.worker_pool import WorkerPool


def _p95(values: list[float]) -> float:
    """Return the 95th percentile from a sorted list."""
    s = sorted(values)
    idx = min(len(s) - 1, int(len(s) * 0.95))
    return s[idx]


SAMPLE_RATE_HZ = 800
FFT_N = 512
WAVEFORM_SECONDS = 4
SPECTRUM_MAX_HZ = 200


def _make_processor(pool: WorkerPool | None = None) -> SignalProcessor:
    return SignalProcessor(
        sample_rate_hz=SAMPLE_RATE_HZ,
        waveform_seconds=WAVEFORM_SECONDS,
        waveform_display_hz=100,
        fft_n=FFT_N,
        spectrum_max_hz=SPECTRUM_MAX_HZ,
        accel_scale_g_per_lsb=1.0 / 256.0,
        worker_pool=pool,
    )


def _inject_signal(proc: SignalProcessor, client_id: str, freq_hz: float) -> None:
    t = np.arange(FFT_N, dtype=np.float64) / SAMPLE_RATE_HZ
    x = (0.05 * np.sin(2.0 * pi * freq_hz * t) * 256.0).astype(np.int16)
    y = (0.03 * np.sin(2.0 * pi * (freq_hz + 10) * t) * 256.0).astype(np.int16)
    z = np.zeros(FFT_N, dtype=np.int16)
    samples = np.stack([x, y, z], axis=1)
    proc.ingest(client_id, samples, sample_rate_hz=SAMPLE_RATE_HZ)


def run_benchmark(
    n_sensors: int = 4,
    n_rounds: int = 10,
    n_ingest_per_round: int = 5,
) -> dict[str, object]:
    """Run the benchmark and return a results dict."""
    client_ids = [f"sensor-{i:02d}" for i in range(n_sensors)]
    freqs = [20.0 + i * 7.5 for i in range(n_sensors)]

    # --- Sequential baseline ---
    proc_seq = _make_processor(pool=None)
    for cid, freq in zip(client_ids, freqs):
        _inject_signal(proc_seq, cid, freq)

    seq_ingest_ms: list[float] = []
    seq_compute_ms: list[float] = []
    for _round in range(n_rounds):
        t0 = time.monotonic()
        for cid, freq in zip(client_ids, freqs):
            for _ in range(n_ingest_per_round):
                _inject_signal(proc_seq, cid, freq)
        seq_ingest_ms.append((time.monotonic() - t0) * 1000)

        t0 = time.monotonic()
        proc_seq.compute_all(client_ids)
        seq_compute_ms.append((time.monotonic() - t0) * 1000)

    # --- Parallel ---
    pool = WorkerPool(max_workers=4, thread_name_prefix="bench-fft")
    proc_par = _make_processor(pool=pool)
    for cid, freq in zip(client_ids, freqs):
        _inject_signal(proc_par, cid, freq)

    par_ingest_ms: list[float] = []
    par_compute_ms: list[float] = []
    for _round in range(n_rounds):
        t0 = time.monotonic()
        for cid, freq in zip(client_ids, freqs):
            for _ in range(n_ingest_per_round):
                _inject_signal(proc_par, cid, freq)
        par_ingest_ms.append((time.monotonic() - t0) * 1000)

        t0 = time.monotonic()
        proc_par.compute_all(client_ids)
        par_compute_ms.append((time.monotonic() - t0) * 1000)

    pool.shutdown()

    # --- Verify output equivalence ---
    # Re-run from fresh processors with identical input
    proc_a = _make_processor(pool=None)
    pool_b = WorkerPool(max_workers=4)
    proc_b = _make_processor(pool=pool_b)
    for cid, freq in zip(client_ids, freqs):
        _inject_signal(proc_a, cid, freq)
        _inject_signal(proc_b, cid, freq)
    res_a = proc_a.compute_all(client_ids)
    res_b = proc_b.compute_all(client_ids)
    pool_b.shutdown()

    output_match = True
    for cid in client_ids:
        for axis in ("x", "y", "z"):
            if abs(res_a[cid][axis]["rms"] - res_b[cid][axis]["rms"]) > 1e-6:
                output_match = False

    return {
        "n_sensors": n_sensors,
        "n_rounds": n_rounds,
        "n_ingest_per_round": n_ingest_per_round,
        "sequential": {
            "ingest_median_ms": round(statistics.median(seq_ingest_ms), 3),
            "ingest_p95_ms": round(_p95(seq_ingest_ms), 3),
            "compute_median_ms": round(statistics.median(seq_compute_ms), 3),
            "compute_p95_ms": round(_p95(seq_compute_ms), 3),
        },
        "parallel": {
            "ingest_median_ms": round(statistics.median(par_ingest_ms), 3),
            "ingest_p95_ms": round(_p95(par_ingest_ms), 3),
            "compute_median_ms": round(statistics.median(par_compute_ms), 3),
            "compute_p95_ms": round(_p95(par_compute_ms), 3),
        },
        "speedup_compute_median": round(
            statistics.median(seq_compute_ms)
            / max(0.001, statistics.median(par_compute_ms)),
            2,
        ),
        "output_equivalent": output_match,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline throughput benchmark")
    parser.add_argument(
        "--sensors", type=int, default=4, help="Number of simulated sensors"
    )
    parser.add_argument(
        "--rounds", type=int, default=10, help="Number of benchmark rounds"
    )
    args = parser.parse_args()

    print(f"Benchmarking with {args.sensors} sensors, {args.rounds} rounds ...\n")
    results = run_benchmark(n_sensors=args.sensors, n_rounds=args.rounds)

    seq = results["sequential"]
    par = results["parallel"]
    print("=" * 60)
    print(f"  {'Metric':<30} {'Sequential':>12} {'Parallel':>12}")
    print("-" * 60)
    print(
        f"  {'Ingest median (ms)':<30} {seq['ingest_median_ms']:>12.3f} {par['ingest_median_ms']:>12.3f}"
    )
    print(
        f"  {'Ingest P95 (ms)':<30} {seq['ingest_p95_ms']:>12.3f} {par['ingest_p95_ms']:>12.3f}"
    )
    print(
        f"  {'Compute median (ms)':<30} {seq['compute_median_ms']:>12.3f} {par['compute_median_ms']:>12.3f}"
    )
    print(
        f"  {'Compute P95 (ms)':<30} {seq['compute_p95_ms']:>12.3f} {par['compute_p95_ms']:>12.3f}"
    )
    print("-" * 60)
    print(f"  {'Compute speedup':<30} {results['speedup_compute_median']:>12.2f}x")
    print(
        f"  {'Output equivalent':<30} {'YES' if results['output_equivalent'] else 'NO':>12}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
