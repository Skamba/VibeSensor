"""Background post-analysis worker for completed recording runs.

``PostAnalysisWorker`` manages a non-evicting queue of run IDs and a single
daemon thread that processes them sequentially. It is entirely decoupled
from the data-collection path and can be tested independently.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock, Thread
from typing import TYPE_CHECKING

from ..runlog import bounded_sample

if TYPE_CHECKING:
    from ..history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

_MAX_POST_ANALYSIS_SAMPLES = 12_000
_WARN_QUEUE_DEPTH = 10


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

    """

    def __init__(
        self,
        history_db: HistoryDB | None,
        error_callback: Callable[[str], None] | None = None,
        clear_error_callback: Callable[[], None] | None = None,
    ) -> None:
        self._history_db = history_db
        self._error_cb = error_callback or (lambda _msg: None)
        self._clear_error_cb = clear_error_callback or (lambda: None)
        self._lock = RLock()
        self._analysis_thread: Thread | None = None
        self._analysis_queue: deque[_QueuedRun] = deque()
        self._analysis_enqueued_run_ids: set[str] = set()
        self._analysis_active_run_id: str | None = None
        self._analysis_active_started_at: float | None = None
        self._analysis_max_queue_depth: int = 0
        self._last_completed_run_id: str | None = None
        self._last_completed_error: str | None = None

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
                daemon=False,
            )
            self._analysis_thread = worker
            worker.start()

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
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
            except Exception:
                LOGGER.exception("Unexpected error in analysis worker for run %s", run_id)
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
        analysis_start = time.monotonic()
        LOGGER.info("Analysis started for run %s", run_id)
        try:
            from ..analysis import summarize_run_data
            from ..runlog import normalize_sample_record

            metadata = db.get_run_metadata(run_id)
            if metadata is None:
                error_msg = "Metadata not found or corrupt; cannot analyse"
                LOGGER.warning("Cannot analyse run %s: metadata not found", run_id)
                with self._lock:
                    self._last_completed_run_id = run_id
                    self._last_completed_error = error_msg
                try:
                    db.store_analysis_error(run_id, error_msg)
                except sqlite3.Error:
                    LOGGER.warning(
                        "Failed to store analysis error for run %s",
                        run_id,
                        exc_info=True,
                    )
                return
            language = str(metadata.get("language") or "en")

            normalized_iter = (
                normalize_sample_record(sample)
                for batch in db.iter_run_samples(run_id, batch_size=1024)
                for sample in batch
            )
            samples, total_sample_count, stride = bounded_sample(
                normalized_iter,
                max_items=_MAX_POST_ANALYSIS_SAMPLES,
            )
            if not samples:
                error_msg = "No samples collected during run"
                LOGGER.warning("Skipping post-analysis for run %s: no samples collected", run_id)
                with self._lock:
                    self._last_completed_run_id = run_id
                    self._last_completed_error = error_msg
                db.store_analysis_error(run_id, error_msg)
                return
            summary = summarize_run_data(
                metadata,
                samples,
                lang=language,
                file_name=run_id,
                include_samples=False,
            )
            summary["analysis_metadata"] = {
                "analyzed_sample_count": len(samples),
                "total_sample_count": total_sample_count,
                "sampling_method": "full" if stride == 1 else f"stride_{stride}",
            }
            if stride > 1:
                from ..report_i18n import tr as _tr

                check = _tr(language, "SUITABILITY_CHECK_ANALYSIS_SAMPLING")
                explanation = _tr(
                    language,
                    "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING",
                    stride=str(stride),
                )
                summary.setdefault("run_suitability", []).append(
                    {
                        "check": check,
                        "check_key": "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
                        "state": "warn",
                        "explanation": explanation,
                    },
                )
            db.store_analysis(run_id, summary)  # type: ignore[arg-type]

            duration_s = time.monotonic() - analysis_start
            LOGGER.info(
                "Analysis completed for run %s: %d samples in %.2fs",
                run_id,
                len(samples),
                duration_s,
            )
            with self._lock:
                self._last_completed_run_id = run_id
                self._last_completed_error = None
            self._clear_error_cb()
        except Exception as exc:
            duration_s = time.monotonic() - analysis_start
            error_msg = f"post-analysis failed for run {run_id}: {exc}"
            self._error_cb(error_msg)
            with self._lock:
                self._last_completed_run_id = run_id
                self._last_completed_error = str(exc)
            LOGGER.warning(
                "Analysis failed for run %s after %.2fs: %s",
                run_id,
                duration_s,
                exc,
                exc_info=True,
            )
            try:
                db.store_analysis_error(run_id, str(exc))
            except sqlite3.Error as store_exc:
                self._error_cb(f"history store_analysis_error failed for run {run_id}: {store_exc}")
                LOGGER.warning("Failed to store analysis error for run %s", run_id, exc_info=True)
