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

__all__ = ["WorkerPool"]

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

    __slots__ = (
        "_alive",
        "_executor",
        "_max_workers",
        "_metrics_lock",
        "_total_tasks",
        "_total_wait_s",
    )

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        thread_name_prefix: str = "vibesensor-worker",
    ) -> None:
        """Initialise the worker pool with the given concurrency limit."""
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
        """Submit a single callable; returns a ``Future``.

        Task execution time is tracked in ``_total_wait_s`` for parity
        with :meth:`map_unordered`.
        """
        with self._metrics_lock:
            if not self._alive:
                raise RuntimeError("WorkerPool is shut down")
            self._total_tasks += 1

        def _timed() -> R:
            t0 = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time.monotonic() - t0
                with self._metrics_lock:
                    self._total_wait_s += elapsed

        return self._executor.submit(_timed)

    def map_unordered(
        self,
        fn: Callable[[T], R],
        items: list[T],
    ) -> dict[T, R]:
        """Run *fn* on each item in parallel; return ``{item: result}`` dict.

        Items whose callable raises are logged and omitted from the result
        dict (fail-open: one broken client doesn't block others).

        Each task is wrapped with the same ``_timed`` logic used by
        :meth:`submit` so that ``total_wait_s`` accumulates per-task
        execution time consistently across both call paths.

        Raises
        ------
        RuntimeError
            If the pool has already been shut down.
        """
        if not items:
            return {}
        with self._metrics_lock:
            if not self._alive:
                raise RuntimeError("WorkerPool is shut down")
            self._total_tasks += len(items)

        def _timed_fn(item: T) -> R:
            t0 = time.monotonic()
            try:
                return fn(item)
            finally:
                elapsed = time.monotonic() - t0
                with self._metrics_lock:
                    self._total_wait_s += elapsed

        futures: dict[Future[R], T] = {
            self._executor.submit(_timed_fn, item): item for item in items
        }

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
        return results

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        """Shut down the pool.  Safe to call multiple times.

        Parameters
        ----------
        wait:
            If ``True`` (default), block until all running futures finish.
        cancel_futures:
            If ``True``, cancel all pending (not yet started) futures before
            shutting down.  Useful for fast teardown on error paths.
            Requires Python ≥ 3.9.
        """
        with self._metrics_lock:
            self._alive = False
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self) -> WorkerPool:
        """Support ``with WorkerPool(...) as pool:`` usage."""
        return self

    def __exit__(self, *_: object) -> None:
        """Shut down the pool when the context manager exits."""
        self.shutdown(wait=True)

    # -- Observability --------------------------------------------------------

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of pool metrics.

        Includes ``avg_wait_s`` (per-task execution time average) which is
        useful for detecting pathologically slow worker payloads.
        """
        with self._metrics_lock:
            avg = round(self._total_wait_s / self._total_tasks, 6) if self._total_tasks > 0 else 0.0
            return {
                "max_workers": self._max_workers,
                "total_tasks": self._total_tasks,
                "total_wait_s": round(self._total_wait_s, 4),
                "avg_wait_s": avg,
                "alive": self._alive,
            }
