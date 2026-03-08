"""Bounded thread-pool wrapper sized for a 4-core Raspberry Pi.

The standard :class:`ThreadPoolExecutor` limits worker threads but keeps an
unbounded internal submission queue. This wrapper adds a bound on total
outstanding work so CPU-heavy tasks (FFT, report generation) apply
backpressure to callers instead of accumulating unbounded queued work.

Contract:

- at most ``max_workers`` tasks run concurrently,
- at most ``max_queue_size`` additional tasks wait to start,
- once ``max_pending_tasks`` is reached, ``submit()`` blocks until capacity
    becomes available, the pool shuts down, or an optional timeout expires,
- ``map_unordered()`` respects the same bound and never floods the executor
    with more than ``max_pending_tasks`` outstanding tasks at once.

Usage::

        pool = WorkerPool(max_workers=4)
        results = pool.map_unordered(compute_metrics, client_ids)
        pool.shutdown()
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from types import TracebackType
from typing import TypedDict, TypeVar

LOGGER = logging.getLogger(__name__)

__all__ = ["WorkerPool"]

T = TypeVar("T")
R = TypeVar("R")


class WorkerPoolStats(TypedDict):
    max_workers: int
    max_queue_size: int
    max_pending_tasks: int
    total_tasks: int
    pending_tasks: int
    queued_tasks: int
    running_tasks: int
    rejected_tasks: int
    total_run_s: float
    avg_run_s: float
    total_submit_wait_s: float
    avg_submit_wait_s: float
    default_submit_timeout_s: float | None
    alive: bool


# Sensible default for a 4-core Raspberry Pi.
DEFAULT_MAX_WORKERS = 4


class WorkerPool:
    """Fixed-size thread pool with bounded outstanding work and metrics.

    Parameters
    ----------
    max_workers:
        Number of worker threads.  Defaults to 4 (one per Pi core).
    max_queue_size:
        Number of additional submitted tasks allowed to wait behind running
        work. Defaults to ``max_workers`` so the pool can absorb one extra
        batch without building an unbounded backlog.
    submit_timeout_s:
        Optional default timeout for waiting on capacity in :meth:`submit`
        and :meth:`map_unordered`. ``None`` means block until capacity or
        shutdown.
    thread_name_prefix:
        Prefix for worker-thread names (aids debugging / profiling).

    """

    __slots__ = (
        "_alive",
        "_condition",
        "_default_submit_timeout_s",
        "_executor",
        "_max_pending_tasks",
        "_max_queue_size",
        "_max_workers",
        "_pending_tasks",
        "_queued_tasks",
        "_rejected_tasks",
        "_running_tasks",
        "_total_tasks",
        "_total_run_s",
        "_total_submit_wait_s",
    )

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_queue_size: int | None = None,
        submit_timeout_s: float | None = None,
        thread_name_prefix: str = "vibesensor-worker",
    ) -> None:
        """Initialise the worker pool with bounded outstanding work."""
        self._max_workers = max(1, int(max_workers))
        self._max_queue_size = (
            self._max_workers if max_queue_size is None else max(0, int(max_queue_size))
        )
        self._max_pending_tasks = self._max_workers + self._max_queue_size
        self._default_submit_timeout_s = self._normalize_timeout(submit_timeout_s)
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._condition = threading.Condition()
        self._total_tasks: int = 0
        self._total_run_s: float = 0.0
        self._total_submit_wait_s: float = 0.0
        self._pending_tasks: int = 0
        self._queued_tasks: int = 0
        self._running_tasks: int = 0
        self._rejected_tasks: int = 0
        self._alive = True

    # -- Internal helpers ----------------------------------------------------

    @staticmethod
    def _normalize_timeout(timeout_s: float | None) -> float | None:
        if timeout_s is None:
            return None
        return max(0.0, float(timeout_s))

    def _ensure_alive_locked(self) -> None:
        if not self._alive:
            raise RuntimeError("WorkerPool is shut down")

    def _reserve_slot(self, timeout_s: float | None) -> None:
        started_waiting_at = time.monotonic()
        with self._condition:
            self._ensure_alive_locked()
            remaining = timeout_s
            while self._pending_tasks >= self._max_pending_tasks:
                if remaining is not None and remaining <= 0:
                    self._rejected_tasks += 1
                    raise TimeoutError("WorkerPool saturated while waiting for capacity")
                self._condition.wait(timeout=remaining)
                self._ensure_alive_locked()
                if timeout_s is not None:
                    remaining = timeout_s - (time.monotonic() - started_waiting_at)
            self._pending_tasks += 1
            self._queued_tasks += 1
            self._total_tasks += 1
            self._total_submit_wait_s += time.monotonic() - started_waiting_at

    def _release_completed_task(self, *, started: bool) -> None:
        with self._condition:
            self._pending_tasks -= 1
            if not started:
                self._queued_tasks -= 1
            self._condition.notify_all()

    # -- Public API -----------------------------------------------------------

    def submit(
        self,
        fn: Callable[..., R],
        *args: object,
        timeout_s: float | None = None,
        **kwargs: object,
    ) -> Future[R]:
        """Submit a single callable and return its ``Future``.

        If the pool is saturated, submission blocks until capacity becomes
        available, the pool shuts down, or the effective timeout expires.

        Parameters
        ----------
        timeout_s:
            Optional per-call capacity wait timeout. ``None`` uses the pool
            default from ``submit_timeout_s``. If the timeout expires before a
            slot becomes available, :class:`TimeoutError` is raised.
        """
        effective_timeout = self._default_submit_timeout_s
        if timeout_s is not None:
            effective_timeout = self._normalize_timeout(timeout_s)
        self._reserve_slot(effective_timeout)
        state = {"started": False}

        def _timed() -> R:
            with self._condition:
                state["started"] = True
                self._queued_tasks -= 1
                self._running_tasks += 1
            started_at = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time.monotonic() - started_at
                with self._condition:
                    self._running_tasks -= 1
                    self._total_run_s += elapsed

        try:
            future = self._executor.submit(_timed)
        except RuntimeError as exc:
            with self._condition:
                self._pending_tasks -= 1
                self._queued_tasks -= 1
                self._total_tasks -= 1
                self._condition.notify_all()
            raise RuntimeError("WorkerPool is shut down") from exc

        future.add_done_callback(
            lambda _: self._release_completed_task(started=bool(state["started"]))
        )
        return future

    def map_unordered(
        self,
        fn: Callable[[T], R],
        items: list[T],
        *,
        timeout_s: float | None = None,
    ) -> dict[T, R]:
        """Run *fn* on each item in parallel; return ``{item: result}`` dict.

        Items whose callable raises are logged and omitted from the result
        dict (fail-open: one broken client doesn't block others).

        Submissions respect the pool's bounded outstanding-task contract.
        At most ``max_pending_tasks`` tasks are submitted at a time, so large
        batches do not create an unbounded executor backlog.

        Raises
        ------
        RuntimeError
            If the pool has already been shut down.
        TimeoutError
            If waiting for capacity exceeds the effective timeout.
        """
        if not items:
            return {}
        results: dict[T, R] = {}
        pending: dict[Future[R], T] = {}
        items_iter = iter(items)
        exhausted = False

        while pending or not exhausted:
            while not exhausted and len(pending) < self._max_pending_tasks:
                try:
                    item = next(items_iter)
                except StopIteration:
                    exhausted = True
                    break
                pending[self.submit(fn, item, timeout_s=timeout_s)] = item

            if not pending:
                continue

            done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for fut in done:
                item = pending.pop(fut)
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

        Blocked submitters are woken immediately and will raise
        :class:`RuntimeError` instead of waiting for capacity.
        """
        with self._condition:
            self._alive = False
            self._condition.notify_all()
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self) -> WorkerPool:
        """Support ``with WorkerPool(...) as pool:`` usage."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Shut down the pool when the context manager exits."""
        self.shutdown(wait=True)

    # -- Observability --------------------------------------------------------

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def max_queue_size(self) -> int:
        return self._max_queue_size

    @property
    def max_pending_tasks(self) -> int:
        return self._max_pending_tasks

    def stats(self) -> WorkerPoolStats:
        """Return a snapshot of pool metrics.

        ``run`` metrics measure time spent executing on worker threads.
        ``submit_wait`` metrics measure caller-side backpressure while waiting
        for a free outstanding-task slot.
        """
        with self._condition:
            avg_run = (
                round(self._total_run_s / self._total_tasks, 6) if self._total_tasks > 0 else 0.0
            )
            avg_submit_wait = (
                round(self._total_submit_wait_s / self._total_tasks, 6)
                if self._total_tasks > 0
                else 0.0
            )
            return {
                "max_workers": self._max_workers,
                "max_queue_size": self._max_queue_size,
                "max_pending_tasks": self._max_pending_tasks,
                "total_tasks": self._total_tasks,
                "pending_tasks": self._pending_tasks,
                "queued_tasks": self._queued_tasks,
                "running_tasks": self._running_tasks,
                "rejected_tasks": self._rejected_tasks,
                "total_run_s": round(self._total_run_s, 4),
                "avg_run_s": avg_run,
                "total_submit_wait_s": round(self._total_submit_wait_s, 4),
                "avg_submit_wait_s": avg_submit_wait,
                "default_submit_timeout_s": self._default_submit_timeout_s,
                "alive": self._alive,
            }
