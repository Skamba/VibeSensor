"""Background post-analysis worker for completed recording runs.

``PostAnalysisWorker`` manages a bounded queue of run IDs and a single
daemon thread that processes them sequentially.  It is entirely decoupled
from the data-collection path and can be tested independently.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from contextlib import nullcontext
from threading import RLock, Thread
from typing import TYPE_CHECKING

from ..runlog import bounded_sample

if TYPE_CHECKING:
    from ..history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

_MAX_POST_ANALYSIS_SAMPLES = 12_000


class PostAnalysisWorker:
    """Threaded worker that runs post-analysis on completed recording runs.

    Parameters
    ----------
    history_db:
        Database handle used to read samples and store analysis results.
    error_callback:
        Called with an error message string whenever a write or analysis
        operation fails.  Typically wired to ``MetricsLogger._set_last_write_error``.
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
        self._analysis_queue: deque[str] = deque(maxlen=100)
        self._analysis_enqueued_run_ids: set[str] = set()
        self._analysis_active_run_id: str | None = None

    # -- public API -----------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """``True`` when analysis work is queued or in progress."""
        with self._lock:
            return bool(
                self._analysis_active_run_id
                or self._analysis_queue
                or (self._analysis_thread and self._analysis_thread.is_alive())
            )

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return self._analysis_active_run_id

    def schedule(self, run_id: str) -> None:
        """Enqueue *run_id* for background analysis."""
        LOGGER.info("Analysis queued for run %s", run_id)
        with self._lock:
            if run_id in self._analysis_enqueued_run_ids or run_id == self._analysis_active_run_id:
                return
            if (
                self._analysis_queue.maxlen is not None
                and len(self._analysis_queue) >= self._analysis_queue.maxlen
            ):
                evicted_id = self._analysis_queue[0]
                self._analysis_enqueued_run_ids.discard(evicted_id)
                LOGGER.warning(
                    "Analysis queue full; evicting run %s to make room for %s",
                    evicted_id,
                    run_id,
                )
            self._analysis_queue.append(run_id)
            self._analysis_enqueued_run_ids.add(run_id)
            self._ensure_worker_running()

    def wait(self, timeout_s: float = 30.0) -> bool:
        """Block until all queued analysis completes or *timeout_s* elapses.

        Returns ``True`` when all work finished, ``False`` on timeout.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            with self._lock:
                worker = self._analysis_thread
                queued = bool(self._analysis_queue)
                active_run = self._analysis_active_run_id is not None
                worker_alive = bool(worker and worker.is_alive())
            if not queued and not active_run and not worker_alive:
                return True
            remaining = deadline - time.monotonic()
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
                daemon=True,
            )
            self._analysis_thread = worker
            worker.start()

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                if not self._analysis_queue:
                    self._analysis_active_run_id = None
                    self._analysis_thread = None
                    return
                run_id = self._analysis_queue.popleft()
                self._analysis_active_run_id = run_id
            try:
                self._run_post_analysis(run_id)
            except Exception:
                LOGGER.exception("Unexpected error in analysis worker for run %s", run_id)
            finally:
                with self._lock:
                    self._analysis_enqueued_run_ids.discard(run_id)
                    self._analysis_active_run_id = None

    def _run_post_analysis(self, run_id: str) -> None:
        """Run thorough post-run analysis and store results in history DB."""
        if self._history_db is None:
            return
        analysis_start = time.monotonic()
        LOGGER.info("Analysis started for run %s", run_id)
        try:
            from ..analysis import summarize_run_data
            from ..runlog import normalize_sample_record

            metadata = self._history_db.get_run_metadata(run_id)
            if metadata is None:
                LOGGER.warning("Cannot analyse run %s: metadata not found", run_id)
                try:
                    self._history_db.store_analysis_error(
                        run_id, "Metadata not found or corrupt; cannot analyse"
                    )
                except Exception:
                    LOGGER.warning(
                        "Failed to store analysis error for run %s", run_id, exc_info=True
                    )
                return
            language = str(metadata.get("language") or "en")

            read_tx = getattr(self._history_db, "read_transaction", None)
            tx_ctx = read_tx() if callable(read_tx) else nullcontext()
            with tx_ctx:
                normalized_iter = (
                    normalize_sample_record(sample)
                    for batch in self._history_db.iter_run_samples(run_id, batch_size=1024)
                    for sample in batch
                )
                samples, total_sample_count, stride = bounded_sample(
                    normalized_iter, max_items=_MAX_POST_ANALYSIS_SAMPLES
                )
            if not samples:
                LOGGER.warning("Skipping post-analysis for run %s: no samples collected", run_id)
                self._history_db.store_analysis_error(run_id, "No samples collected during run")
                return
            summary = summarize_run_data(
                metadata, samples, lang=language, file_name=run_id, include_samples=False
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
                    }
                )
            try:
                from dataclasses import asdict

                from ..analysis import map_summary

                report_data = map_summary(summary)
                summary["_report_template_data"] = asdict(report_data)
            except Exception:
                LOGGER.error(
                    "Failed to build ReportTemplateData for run %s; "
                    "PDF will rebuild from summary on request",
                    run_id,
                    exc_info=True,
                )

            self._history_db.store_analysis(run_id, summary)

            duration_s = time.monotonic() - analysis_start
            LOGGER.info(
                "Analysis completed for run %s: %d samples in %.2fs",
                run_id,
                len(samples),
                duration_s,
            )
        except Exception as exc:
            duration_s = time.monotonic() - analysis_start
            self._error_cb(f"post-analysis failed for run {run_id}: {exc}")
            LOGGER.warning(
                "Analysis failed for run %s after %.2fs: %s",
                run_id,
                duration_s,
                exc,
                exc_info=True,
            )
            try:
                self._history_db.store_analysis_error(run_id, str(exc))
            except Exception as store_exc:
                self._error_cb(f"history store_analysis_error failed for run {run_id}: {store_exc}")
                LOGGER.warning("Failed to store analysis error for run %s", run_id, exc_info=True)
