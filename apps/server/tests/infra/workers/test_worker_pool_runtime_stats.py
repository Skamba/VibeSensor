"""Behavior tests for worker-pool runtime stats and shutdown edges."""

from __future__ import annotations

import time

from vibesensor.infra.workers.worker_pool import WorkerPool


class TestWorkerPoolRuntimeStats:
    """Cover direct submit behavior, runtime stats, and wait-free shutdown."""

    def test_submit_returns_future(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            fut = pool.submit(lambda: 42)
            assert fut.result(timeout=2) == 42
        finally:
            pool.shutdown()

    def test_stats_tracks_total_run_s(self) -> None:
        pool = WorkerPool(max_workers=1)
        try:
            pool.map_unordered(lambda x: time.sleep(0.01) or x, [1, 2])
            stats = pool.stats()
            assert stats["total_run_s"] > 0
            assert stats["avg_run_s"] > 0
            assert stats["total_tasks"] == 2
            assert stats["pending_tasks"] == 0
            assert stats["queued_tasks"] == 0
            assert stats["running_tasks"] == 0
        finally:
            pool.shutdown()

    def test_max_workers_clamped_to_one(self) -> None:
        pool = WorkerPool(max_workers=0)
        try:
            assert pool.max_workers == 1
        finally:
            pool.shutdown()

    def test_shutdown_wait_false(self) -> None:
        pool = WorkerPool(max_workers=2)
        pool.shutdown(wait=False)
        assert pool.stats()["alive"] is False
