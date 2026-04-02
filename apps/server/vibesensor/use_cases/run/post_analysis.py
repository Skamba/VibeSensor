"""Background post-analysis worker for completed recording runs.

``PostAnalysisWorker`` manages a non-evicting queue of run IDs and a single
daemon thread that processes them sequentially. It is entirely decoupled
from the data-collection path and can be tested independently.

Run loading/downsampling, persisted-analysis building, and execution/writeback
policy live in focused collaborators; this module owns only queue/thread
lifecycle, health state, and callback forwarding.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, RLock, Thread

from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.ports import RunPersistence
from vibesensor.use_cases.run.post_analysis_executor import (
    PostAnalysisAttemptResult,
    PostAnalysisRunner,
    execute_post_analysis,
)
from vibesensor.use_cases.run.post_analysis_outcomes import (
    PostAnalysisExecutionResult,
    PostAnalysisExecutionRetryableFailure,
    PostAnalysisExecutionSuccess,
    execution_callback_errors,
)
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary

LOGGER = logging.getLogger(__name__)

_WARN_QUEUE_DEPTH = 10
_RETRY_DELAYS_S = (0.5, 1.0, 2.0)


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


class PostAnalysisWorker:
    """Threaded worker that runs post-analysis on completed recording runs.

    Parameters
    ----------
    history_db:
        Database handle used to read samples and store analysis results.
    error_callback:
        Called with an error message string whenever a write or analysis
        operation fails.  Typically wired to the persistence coordinator's
        ``last_write_error`` attribute.
    clear_error_callback:
        Called (no args) when an error condition is resolved.
    analysis_runner:
        Callable that builds the persisted analysis summary once metadata and
        samples have been loaded. `RunRecorder` injects the concrete
        diagnostics implementation.

    Notes
    -----
    The queue/thread orchestration depends only on the injected persistence
    port, analysis runner, and error callbacks.

    """

    def __init__(
        self,
        history_db: RunPersistence | None,
        error_callback: Callable[[str], None] | None = None,
        clear_error_callback: Callable[[], None] | None = None,
        analysis_runner: PostAnalysisRunner = build_post_analysis_summary,
    ) -> None:
        self._history_db = history_db
        self._error_cb = error_callback or (lambda _msg: None)
        self._clear_error_cb = clear_error_callback or (lambda: None)
        self._analysis_runner = analysis_runner
        self._lock = RLock()
        self._analysis_thread: Thread | None = None
        self._analysis_queue: deque[_QueuedRun] = deque()
        self._analysis_enqueued_run_ids: set[str] = set()
        self._analysis_active_run_id: str | None = None
        self._analysis_active_started_at: float | None = None
        self._analysis_max_queue_depth: int = 0
        self._last_completed_run_id: str | None = None
        self._last_completed_error: str | None = None
        self._shutdown_event = Event()

    # -- public API -----------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """``True`` when analysis work is queued or in progress."""
        with self._lock:
            return bool(
                self._analysis_active_run_id
                or self._analysis_queue
                or (self._analysis_thread and self._analysis_thread.is_alive()),
            )

    @property
    def active_run_id(self) -> str | None:
        """Return the run ID currently being analysed, or ``None``."""
        with self._lock:
            return self._analysis_active_run_id

    def snapshot(self) -> PostAnalysisHealthSnapshot:
        """Return queue depth and active-run timing for health reporting."""
        with self._lock:
            oldest_queued_at = self._analysis_queue[0].enqueued_at if self._analysis_queue else None
            return PostAnalysisHealthSnapshot(
                queue_depth=len(self._analysis_queue),
                active_run_id=self._analysis_active_run_id,
                active_started_at=self._analysis_active_started_at,
                oldest_queued_at=oldest_queued_at,
                max_queue_depth=self._analysis_max_queue_depth,
                last_completed_run_id=self._last_completed_run_id,
                last_completed_error=self._last_completed_error,
            )

    def schedule(self, run_id: str) -> None:
        """Enqueue *run_id* for background analysis."""
        LOGGER.info("Analysis queued for run %s", run_id)
        with self._lock:
            if self._shutdown_event.is_set():
                LOGGER.info("Ignoring post-analysis schedule for %s during shutdown", run_id)
                return
            if run_id in self._analysis_enqueued_run_ids or run_id == self._analysis_active_run_id:
                return
            self._analysis_queue.append(_QueuedRun(run_id=run_id, enqueued_at=time.time()))
            self._analysis_enqueued_run_ids.add(run_id)
            queue_depth = len(self._analysis_queue)
            self._analysis_max_queue_depth = max(
                self._analysis_max_queue_depth,
                queue_depth,
            )
            self._ensure_worker_running()
        if queue_depth >= _WARN_QUEUE_DEPTH:
            LOGGER.warning(
                "Post-analysis queue depth reached %d; analysis may be falling behind",
                queue_depth,
            )

    def wait(self, timeout_s: float = 30.0) -> bool:
        """Block until all queued analysis completes or *timeout_s* elapses.

        Returns ``True`` when all work finished, ``False`` on timeout.
        """
        _monotonic = time.monotonic
        lock = self._lock
        deadline = _monotonic() + max(0.0, timeout_s)
        while True:
            with lock:
                worker = self._analysis_thread
                queued = bool(self._analysis_queue)
                active_run = self._analysis_active_run_id is not None
                worker_alive = bool(worker and worker.is_alive())
            if not queued and not active_run and not worker_alive:
                return True
            remaining = deadline - _monotonic()
            if remaining <= 0:
                LOGGER.warning(
                    "wait_for_post_analysis timed out after %.1fs "
                    "(queued=%s, active=%s, worker_alive=%s)",
                    timeout_s,
                    queued,
                    active_run,
                    worker_alive,
                )
                return False
            if worker is not None and worker_alive:
                worker.join(timeout=min(0.2, remaining))
            else:
                time.sleep(min(0.05, remaining))

    def shutdown(self, timeout_s: float = 5.0) -> bool:
        """Cancel pending post-analysis work and wait briefly for the worker to exit."""
        self._shutdown_event.set()
        with self._lock:
            self._analysis_queue.clear()
            self._analysis_enqueued_run_ids.clear()
        return self.wait(timeout_s)

    # -- internals ------------------------------------------------------------

    def _ensure_worker_running(self) -> None:
        """Start a new worker thread if none is alive.

        Must be called while holding ``self._lock``.
        """
        worker = self._analysis_thread
        if worker is None or not worker.is_alive():
            worker = Thread(
                target=self._worker_loop,
                name="metrics-post-analysis-worker",
                daemon=True,
            )
            self._analysis_thread = worker
            worker.start()

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                if self._shutdown_event.is_set():
                    self._analysis_active_run_id = None
                    self._analysis_active_started_at = None
                    self._analysis_thread = None
                    return
                if not self._analysis_queue:
                    self._analysis_active_run_id = None
                    self._analysis_active_started_at = None
                    self._analysis_thread = None
                    return
                queued = self._analysis_queue.popleft()
                run_id = queued.run_id
                self._analysis_active_run_id = run_id
                self._analysis_active_started_at = time.time()
            try:
                self._run_post_analysis(run_id)
            except Exception as exc:
                self._record_unexpected_worker_failure(run_id, exc)
            finally:
                with self._lock:
                    self._analysis_enqueued_run_ids.discard(run_id)
                    self._analysis_active_run_id = None
                    self._analysis_active_started_at = None

    def _run_post_analysis(self, run_id: str) -> None:
        """Run thorough post-run analysis and store results in history DB."""
        db = self._history_db
        if db is None:
            return
        retry_index = 0
        while True:
            if self._shutdown_event.is_set():
                return
            defer_retryable_error_storage = retry_index < len(_RETRY_DELAYS_S)
            result: PostAnalysisAttemptResult = execute_post_analysis(
                run_id=run_id,
                db=db,
                analysis_runner=self._analysis_runner,
                defer_retryable_error_storage=defer_retryable_error_storage,
            )
            if isinstance(result, PostAnalysisExecutionRetryableFailure):
                delay_s = _RETRY_DELAYS_S[retry_index]
                self._record_retryable_failure(
                    result,
                    attempt=retry_index + 1,
                    delay_s=delay_s,
                )
                retry_index += 1
                if self._shutdown_event.wait(delay_s):
                    return
                continue
            self._record_execution_result(result)
            return

    def _record_retryable_failure(
        self,
        result: PostAnalysisExecutionRetryableFailure,
        *,
        attempt: int,
        delay_s: float,
    ) -> None:
        LOGGER.warning(
            "Retrying post-analysis for run %s in %.1fs after transient failure (retry %d/%d): %s",
            result.run_id,
            delay_s,
            attempt,
            len(_RETRY_DELAYS_S),
            result.error_message,
        )
        for error_msg in result.callback_errors:
            self._error_cb(error_msg)

    def _record_execution_result(
        self,
        result: PostAnalysisExecutionResult,
    ) -> None:
        completed_error = None
        if not isinstance(result, PostAnalysisExecutionSuccess):
            completed_error = result.completed_error

        with self._lock:
            self._last_completed_run_id = result.run_id
            self._last_completed_error = completed_error

        if isinstance(result, PostAnalysisExecutionSuccess):
            self._clear_error_cb()
            return

        for error_msg in execution_callback_errors(result):
            self._error_cb(error_msg)

    def _record_unexpected_worker_failure(self, run_id: str, exc: Exception) -> None:
        completed_error = bounded_failure_message(exc)
        with self._lock:
            self._last_completed_run_id = run_id
            self._last_completed_error = completed_error
        self._error_cb(f"post-analysis failed for run {run_id}: {completed_error}")
        LOGGER.exception("Unexpected error in analysis worker for run %s", run_id)
