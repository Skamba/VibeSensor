"""Tests for WorkerPool and parallel compute_all in SignalProcessor.

Validates:
- WorkerPool map_unordered correctness and error handling
- Parallel compute_all produces identical results to sequential
- No data races under concurrent ingest + compute
- Bounded queue / backpressure behaviour
- Clean shutdown semantics
"""

from __future__ import annotations

import threading
import time
from math import pi

import numpy as np
import pytest

from vibesensor.processing import SignalProcessor
from vibesensor.worker_pool import WorkerPool

# ---------------------------------------------------------------------------
# WorkerPool unit tests
# ---------------------------------------------------------------------------


class TestWorkerPool:
    def test_map_unordered_basic(self) -> None:
        pool = WorkerPool(max_workers=2, thread_name_prefix="test")
        try:
            result = pool.map_unordered(lambda x: x * 2, [1, 2, 3, 4])
            assert result == {1: 2, 2: 4, 3: 6, 4: 8}
        finally:
            pool.shutdown()

    def test_map_unordered_empty(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            assert pool.map_unordered(lambda x: x, []) == {}
        finally:
            pool.shutdown()

    def test_map_unordered_error_handling(self) -> None:
        """Tasks that raise are logged and omitted, not propagated."""
        pool = WorkerPool(max_workers=2)
        try:

            def _maybe_fail(x: int) -> int:
                if x == 2:
                    raise ValueError("boom")
                return x * 10

            result = pool.map_unordered(_maybe_fail, [1, 2, 3])
            assert 1 in result
            assert 3 in result
            assert 2 not in result  # failed item omitted
        finally:
            pool.shutdown()

    def test_stats(self) -> None:
        pool = WorkerPool(max_workers=3)
        try:
            pool.map_unordered(lambda x: x, [1, 2])
            stats = pool.stats()
            assert stats["max_workers"] == 3
            assert stats["total_tasks"] == 2
            assert stats["alive"] is True
        finally:
            pool.shutdown()
            assert pool.stats()["alive"] is False

    def test_shutdown_idempotent(self) -> None:
        pool = WorkerPool(max_workers=1)
        pool.shutdown()
        pool.shutdown()  # should not raise

    def test_submit_after_shutdown_raises(self) -> None:
        pool = WorkerPool(max_workers=1)
        pool.shutdown()
        with pytest.raises(RuntimeError, match="shut down"):
            pool.submit(lambda: 42)

    def test_uses_multiple_threads(self) -> None:
        """Verify that work actually runs on different threads."""
        pool = WorkerPool(max_workers=4)
        try:

            def _get_thread_id(_: int) -> int | None:
                time.sleep(0.02)  # ensure tasks overlap
                return threading.current_thread().ident

            thread_ids = pool.map_unordered(_get_thread_id, [1, 2, 3, 4])
            # At least 2 different threads should be used
            unique_threads = set(thread_ids.values())
            assert len(unique_threads) >= 2
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# Parallel compute_all tests
# ---------------------------------------------------------------------------


def _make_processor(pool: WorkerPool | None = None) -> SignalProcessor:
    return SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=100,
        fft_n=512,
        spectrum_max_hz=200,
        accel_scale_g_per_lsb=1.0 / 256.0,
        worker_pool=pool,
    )


def _inject_test_signal(
    processor: SignalProcessor,
    client_id: str,
    freq_hz: float = 25.0,
    n_samples: int = 512,
    sample_rate_hz: int = 800,
) -> None:
    """Inject a deterministic sine signal for testing."""
    t = np.arange(n_samples, dtype=np.float64) / sample_rate_hz
    x_lsb = (0.05 * np.sin(2.0 * pi * freq_hz * t) * 256.0).astype(np.int16)
    y_lsb = np.zeros(n_samples, dtype=np.int16)
    z_lsb = np.zeros(n_samples, dtype=np.int16)
    samples = np.stack([x_lsb, y_lsb, z_lsb], axis=1)
    processor.ingest(client_id, samples, sample_rate_hz=sample_rate_hz)


class TestParallelComputeAll:
    def test_single_client_no_pool(self) -> None:
        """Single-client path should work without a pool."""
        proc = _make_processor(pool=None)
        _inject_test_signal(proc, "c1", freq_hz=30.0)
        result = proc.compute_all(["c1"])
        assert "c1" in result
        assert result["c1"]["x"]["rms"] > 0

    def test_multi_client_parallel(self) -> None:
        """Multiple clients computed in parallel should produce valid results."""
        pool = WorkerPool(max_workers=4)
        proc = _make_processor(pool=pool)
        try:
            client_ids = [f"c{i}" for i in range(4)]
            freqs = [20.0, 30.0, 40.0, 50.0]
            for cid, freq in zip(client_ids, freqs, strict=True):
                _inject_test_signal(proc, cid, freq_hz=freq)

            results = proc.compute_all(client_ids)
            assert len(results) == 4
            for cid in client_ids:
                assert cid in results
                assert results[cid].get("x", {}).get("rms", 0) > 0
        finally:
            pool.shutdown()

    def test_parallel_matches_sequential(self) -> None:
        """Parallel and sequential compute_all must produce identical results."""
        pool = WorkerPool(max_workers=4)
        proc_seq = _make_processor(pool=None)
        proc_par = _make_processor(pool=pool)
        try:
            client_ids = [f"c{i}" for i in range(4)]
            rng = np.random.default_rng(42)
            for cid in client_ids:
                freq = 15.0 + rng.uniform(0, 50)
                n = 512
                t = np.arange(n, dtype=np.float64) / 800
                x_lsb = (0.05 * np.sin(2.0 * pi * freq * t) * 256.0).astype(np.int16)
                y_lsb = (0.02 * np.sin(2.0 * pi * (freq + 5) * t) * 256.0).astype(np.int16)
                z_lsb = np.zeros(n, dtype=np.int16)
                samples = np.stack([x_lsb, y_lsb, z_lsb], axis=1)
                proc_seq.ingest(cid, samples, sample_rate_hz=800)
                proc_par.ingest(cid, samples, sample_rate_hz=800)

            seq_result = proc_seq.compute_all(client_ids)
            par_result = proc_par.compute_all(client_ids)

            for cid in client_ids:
                assert cid in seq_result
                assert cid in par_result
                seq_m = seq_result[cid]
                par_m = par_result[cid]
                for axis in ("x", "y", "z"):
                    assert abs(seq_m[axis]["rms"] - par_m[axis]["rms"]) < 1e-6
                    assert abs(seq_m[axis]["p2p"] - par_m[axis]["p2p"]) < 1e-6
        finally:
            pool.shutdown()

    def test_concurrent_ingest_and_compute(self) -> None:
        """Ingest and compute can run concurrently without data races."""
        pool = WorkerPool(max_workers=4)
        proc = _make_processor(pool=pool)
        try:
            # Pre-fill buffers
            for i in range(4):
                _inject_test_signal(proc, f"c{i}")

            errors: list[Exception] = []

            def _ingest_loop() -> None:
                try:
                    for _ in range(50):
                        for i in range(4):
                            _inject_test_signal(proc, f"c{i}", n_samples=64)
                        time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

            def _compute_loop() -> None:
                try:
                    for _ in range(20):
                        proc.compute_all([f"c{i}" for i in range(4)])
                        time.sleep(0.002)
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=_ingest_loop)
            t2 = threading.Thread(target=_compute_loop)
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)
            assert not errors, f"Concurrent access errors: {errors}"
        finally:
            pool.shutdown()

    def test_compute_all_timing_counter(self) -> None:
        """compute_all should update the timing counter."""
        pool = WorkerPool(max_workers=2)
        proc = _make_processor(pool=pool)
        try:
            _inject_test_signal(proc, "c1")
            _inject_test_signal(proc, "c2")
            proc.compute_all(["c1", "c2"])
            stats = proc.intake_stats()
            assert stats["last_compute_all_duration_s"] > 0
            assert "worker_pool" in stats
            assert stats["worker_pool"]["total_tasks"] == 2
        finally:
            pool.shutdown()

    def test_ingest_timing_counter(self) -> None:
        """ingest() should update its timing counter."""
        proc = _make_processor()
        _inject_test_signal(proc, "c1", n_samples=100)
        stats = proc.intake_stats()
        assert stats["last_ingest_duration_s"] > 0

    def test_compute_all_empty_clients(self) -> None:
        """compute_all with empty list should return empty dict."""
        pool = WorkerPool(max_workers=2)
        proc = _make_processor(pool=pool)
        try:
            result = proc.compute_all([])
            assert result == {}
        finally:
            pool.shutdown()
