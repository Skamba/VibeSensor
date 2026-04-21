"""Failure-recording helpers for background post-analysis."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import aiosqlite

from vibesensor.shared.failure_utils import bounded_failure_message
from vibesensor.shared.ports import RunPersistence

LOGGER = logging.getLogger(__name__)

__all__ = ["UnexpectedPostAnalysisBug", "UnexpectedPostAnalysisBugRecorder"]


@dataclass(frozen=True, slots=True)
class UnexpectedPostAnalysisBug:
    """Recorded bug details from the outer post-analysis worker safeguard."""

    completed_error: str
    callback_error: str


class UnexpectedPostAnalysisBugRecorder:
    """Persist and surface unexpected worker bugs outside operational post-analysis paths."""

    __slots__ = ("_error_cb", "_history_db")

    def __init__(
        self,
        *,
        history_db: RunPersistence | None,
        error_callback: Callable[[str], None],
    ) -> None:
        self._history_db = history_db
        self._error_cb = error_callback

    def record_bug(self, *, run_id: str, exc: Exception) -> UnexpectedPostAnalysisBug:
        detail = bounded_failure_message(exc)
        recorded_bug = UnexpectedPostAnalysisBug(
            completed_error=f"Unexpected post-analysis worker bug: {detail}",
            callback_error=f"post-analysis worker bug for run {run_id}: {detail}",
        )
        self._store_analysis_error(
            run_id=run_id,
            completed_error=recorded_bug.completed_error,
        )
        self._error_cb(recorded_bug.callback_error)
        LOGGER.exception("Unexpected post-analysis worker bug for run %s", run_id)
        return recorded_bug

    def _store_analysis_error(self, *, run_id: str, completed_error: str) -> None:
        db = self._history_db
        if db is None:
            return
        astore = getattr(db, "astore_analysis_error", None)
        if not callable(astore):
            return
        try:
            runner = getattr(db, "_run_on_engine_loop", None)
            if callable(runner):
                runner(astore(run_id, completed_error))
            else:
                import asyncio as _asyncio

                _asyncio.run(astore(run_id, completed_error))
        except (aiosqlite.Error, OSError):
            LOGGER.exception(
                "Failed to persist unexpected analysis failure for run %s",
                run_id,
            )
