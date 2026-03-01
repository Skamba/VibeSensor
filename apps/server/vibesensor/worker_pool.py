"""Lightweight thread-pool wrapper sized for a 4-core Raspberry Pi.

Provides bounded concurrency with explicit backpressure so CPU-heavy work
(FFT, report generation) can run on all cores without starving the ingest
path or growing memory unboundedly.

Usage::

    pool = WorkerPool(max_workers=4)
    results = pool.map(compute_metrics, client_ids)
    pool.shutdown()
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# Sensible default for a 4-core Raspberry Pi.
DEFAULT_MAX_WORKERS = 4


class WorkerPool:
    """Fixed-size thread pool with lightweight metrics.

    Parameters
    ----------
    max_workers:
        Number of worker threads.  Defaults to 4 (one per Pi core).
    thread_name_prefix:
        Prefix for worker-thread names (aids debugging / profiling).
    """

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        thread_name_prefix: str = "vibesensor-worker",
    ) -> None:
        self._max_workers = max(1, int(max_workers))
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._total_tasks: int = 0
        self._total_wait_s: float = 0.0
        self._metrics_lock = threading.Lock()
        self._alive = True

    # -- Public API -----------------------------------------------------------

    def submit(self, fn: Callable[..., R], *args: Any, **kwargs: Any) -> Future[R]:
        """Submit a single callable; returns a ``Future``."""
        if not self._alive:
            raise RuntimeError("WorkerPool is shut down")
        with self._metrics_lock:
            self._total_tasks += 1
        return self._executor.submit(fn, *args, **kwargs)

    def map_unordered(
        self,
        fn: Callable[[T], R],
        items: list[T],
    ) -> dict[T, R]:
        """Run *fn* on each item in parallel; return ``{item: result}`` dict.

        Items whose callable raises are logged and omitted from the result
        dict (fail-open: one broken client doesn't block others).
        """
        if not items:
            return {}
        t0 = time.monotonic()
        futures: dict[Future[R], T] = {}
        for item in items:
            with self._metrics_lock:
                self._total_tasks += 1
            fut = self._executor.submit(fn, item)
            futures[fut] = item

        results: dict[T, R] = {}
        for fut, item in futures.items():
            try:
                results[item] = fut.result()
            except Exception:
                LOGGER.warning(
                    "WorkerPool task failed for item %r; skipping.",
                    item,
                    exc_info=True,
                )
        elapsed = time.monotonic() - t0
        with self._metrics_lock:
            self._total_wait_s += elapsed
        return results

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the pool.  Safe to call multiple times."""
        self._alive = False
        self._executor.shutdown(wait=wait)

    # -- Observability --------------------------------------------------------

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def stats(self) -> dict[str, Any]:
        return {
            "max_workers": self._max_workers,
            "total_tasks": self._total_tasks,
            "total_wait_s": round(self._total_wait_s, 4),
            "alive": self._alive,
        }
