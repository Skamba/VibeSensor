"""Queue and health state for background post-analysis."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _QueuedRun:
    run_id: str
    enqueued_at: float


@dataclass(frozen=True, slots=True)
class PostAnalysisHealthSnapshot:
    queue_depth: int
    active_run_id: str | None
    active_started_at: float | None
    oldest_queued_at: float | None
    max_queue_depth: int
    last_completed_run_id: str | None
    last_completed_error: str | None


class PostAnalysisState:
    """Mutable queue/health state for the threaded post-analysis worker."""

    __slots__ = (
        "_queue",
        "_enqueued_run_ids",
        "active_run_id",
        "active_started_at",
        "max_queue_depth",
        "last_completed_run_id",
        "last_completed_error",
    )

    def __init__(self) -> None:
        self._queue: deque[_QueuedRun] = deque()
        self._enqueued_run_ids: set[str] = set()
        self.active_run_id: str | None = None
        self.active_started_at: float | None = None
        self.max_queue_depth = 0
        self.last_completed_run_id: str | None = None
        self.last_completed_error: str | None = None

    def is_active(self, *, worker_alive: bool) -> bool:
        return bool(self.active_run_id or self._queue or worker_alive)

    def snapshot(self) -> PostAnalysisHealthSnapshot:
        oldest_queued_at = self._queue[0].enqueued_at if self._queue else None
        return PostAnalysisHealthSnapshot(
            queue_depth=len(self._queue),
            active_run_id=self.active_run_id,
            active_started_at=self.active_started_at,
            oldest_queued_at=oldest_queued_at,
            max_queue_depth=self.max_queue_depth,
            last_completed_run_id=self.last_completed_run_id,
            last_completed_error=self.last_completed_error,
        )

    def enqueue(self, run_id: str, *, enqueued_at: float) -> int | None:
        if run_id in self._enqueued_run_ids or run_id == self.active_run_id:
            return None
        self._queue.append(_QueuedRun(run_id=run_id, enqueued_at=enqueued_at))
        self._enqueued_run_ids.add(run_id)
        queue_depth = len(self._queue)
        self.max_queue_depth = max(self.max_queue_depth, queue_depth)
        return queue_depth

    def start_next(self, *, started_at: float) -> str | None:
        if not self._queue:
            self.active_run_id = None
            self.active_started_at = None
            return None
        queued = self._queue.popleft()
        self.active_run_id = queued.run_id
        self.active_started_at = started_at
        return queued.run_id

    def finish_active(self, run_id: str) -> None:
        self._enqueued_run_ids.discard(run_id)
        self.active_run_id = None
        self.active_started_at = None

    def mark_completed(self, run_id: str, *, error: str | None) -> None:
        self.last_completed_run_id = run_id
        self.last_completed_error = error

    def clear_pending(self) -> None:
        self._queue.clear()
        self._enqueued_run_ids.clear()

