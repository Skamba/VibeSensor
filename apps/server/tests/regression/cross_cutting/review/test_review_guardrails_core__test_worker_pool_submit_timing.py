"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import time

from vibesensor.worker_pool import WorkerPool

_PROCESSING_DEFAULTS = dict(
    waveform_seconds=8,
    waveform_display_hz=120,
    ui_push_hz=10,
    ui_heavy_push_hz=4,
    fft_update_hz=4,
    fft_n=2048,
    spectrum_min_hz=5.0,
    client_ttl_seconds=120,
    accel_scale_g_per_lsb=None,
)


class TestWorkerPoolSubmitTiming:
    def test_submit_tracks_wait_time(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            future = pool.submit(time.sleep, 0.05)
            future.result()
            stats = pool.stats()
            assert stats["total_tasks"] == 1
            assert stats["total_wait_s"] >= 0.04
        finally:
            pool.shutdown()

    def test_submit_timing_accumulates(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            futures = [pool.submit(time.sleep, 0.02) for _ in range(3)]
            for f in futures:
                f.result()
            stats = pool.stats()
            assert stats["total_tasks"] == 3
            assert stats["total_wait_s"] >= 0.05
        finally:
            pool.shutdown()
