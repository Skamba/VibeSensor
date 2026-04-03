"""Failure-recording helpers for background post-analysis."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.ports import RunPersistence

LOGGER = logging.getLogger(__name__)


class UnexpectedPostAnalysisFailureRecorder:
    """Persist and surface unexpected worker failures outside queue/thread control."""

    __slots__ = ("_error_cb", "_history_db")

    def __init__(
        self,
        *,
        history_db: RunPersistence | None,
        error_callback: Callable[[str], None],
    ) -> None:
        self._history_db = history_db
        self._error_cb = error_callback

    def record(self, *, run_id: str, exc: Exception) -> str:
        completed_error = bounded_failure_message(exc)
        self._store_analysis_error(run_id=run_id, completed_error=completed_error)
        self._error_cb(f"post-analysis failed for run {run_id}: {completed_error}")
        LOGGER.exception("Unexpected error in analysis worker for run %s", run_id)
        return completed_error

    def _store_analysis_error(self, *, run_id: str, completed_error: str) -> None:
        db = self._history_db
        if db is None:
            return
        store_analysis_error = getattr(db, "store_analysis_error", None)
        if not callable(store_analysis_error):
            return
        try:
            store_analysis_error(run_id, completed_error)
        except (sqlite3.Error, OSError):
            LOGGER.exception(
                "Failed to persist unexpected analysis failure for run %s",
                run_id,
            )
