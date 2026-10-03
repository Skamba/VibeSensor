"""Post-analysis execution for one completed run, as straight-line steps.

``execute_post_analysis`` runs these steps in order and logs one structured
``post_analysis_step`` line per step (status ``ok``/``skipped``/``degraded``/
``failed`` plus timing and step details):

1. ``load_run`` loads metadata and summary rows. Missing metadata or an empty
   run ends the attempt with a stored terminal error.
2. ``build_input`` shapes the canonical ``PostAnalysisRunInput`` (summary rows
   with FFT peaks recomputed from the raw capture when it is available).
3. ``analyze`` runs the summary analysis (findings, top causes, most likely
   origin) that both the UI and the PDF report read.
4. ``persist_analysis`` stores the persisted analysis.

A storage or memory error (``sqlite3.Error``, ``OSError``, ``MemoryError``)
or a run too short for strength metrics aborts the sequence. The error is
either deferred for a retry or stored as the run's analysis error.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from vibesensor.analysis._validation import MissingStrengthMetricsError
from vibesensor.analysis.post_analysis_input import (
    PostAnalysisRunInput,
    build_post_analysis_input,
)
from vibesensor.analysis.post_analysis_loader import (
    EmptyPostAnalysisSamples,
    MissingPostAnalysisMetadata,
    PostAnalysisLoadResult,
    load_post_analysis_run,
)
from vibesensor.analysis.post_analysis_outcomes import (
    PostAnalysisAttemptResult,
    PostAnalysisExecutionMissingMetadata,
    PostAnalysisExecutionNoSamples,
    PostAnalysisExecutionPersistenceFailure,
    PostAnalysisExecutionResult,
    PostAnalysisExecutionRetryableFailure,
    PostAnalysisExecutionSuccess,
    is_retryable_post_analysis_error,
)
from vibesensor.common.json_types import JsonObject
from vibesensor.common.structured_logging import log_extra
from vibesensor.summary.persisted_analysis import PersistedAnalysis

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

# MissingStrengthMetricsError is a data outcome (recording shorter than one
# analysis window), so it fails the run instead of halting the worker.
_STEP_ERRORS = (sqlite3.Error, OSError, MemoryError, MissingStrengthMetricsError)


class PostAnalysisRunner(Protocol):
    """Injected boundary for building the stored post-stop analysis summary."""

    def __call__(self, run: PostAnalysisRunInput) -> PersistedAnalysis | Mapping[str, object]: ...


class PostAnalysisLoader(Protocol):
    """Injected boundary for loading metadata and samples for a completed run."""

    def __call__(
        self,
        *,
        run_id: str,
        db: HistoryDB,
    ) -> PostAnalysisLoadResult: ...


@dataclass(frozen=True, slots=True)
class PostAnalysisExecutionConfig:
    analysis_runner: PostAnalysisRunner
    load_run: PostAnalysisLoader = load_post_analysis_run
    defer_retryable_error_storage: bool = False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def execute_post_analysis(
    *,
    run_id: str,
    db: HistoryDB,
    config: PostAnalysisExecutionConfig,
) -> PostAnalysisAttemptResult:
    analysis_start = time.monotonic()
    LOGGER.info(
        "Analysis started for run %s",
        run_id,
        extra=log_extra(event="post_analysis_started", run_id=run_id),
    )
    try:
        with _step(run_id, "load_run") as step:
            load_result = config.load_run(run_id=run_id, db=db)
            if isinstance(load_result, MissingPostAnalysisMetadata | EmptyPostAnalysisSamples):
                failure_kind = (
                    "missing_metadata"
                    if isinstance(load_result, MissingPostAnalysisMetadata)
                    else "no_samples"
                )
                step.update(status="failed", failure_kind=failure_kind)
            else:
                step.update(
                    sample_count=len(load_result.samples),
                    raw_capture_available=load_result.raw_capture is not None,
                    raw_capture_manifest_available=(load_result.raw_capture_manifest is not None),
                )
        if isinstance(load_result, MissingPostAnalysisMetadata | EmptyPostAnalysisSamples):
            return _store_load_error(
                db=db,
                run_id=run_id,
                completed_error=load_result.error_message,
                kind=failure_kind,
            )
        loaded = load_result

        with _step(run_id, "build_input") as step:
            run_input = build_post_analysis_input(loaded)
            step.update(
                summary_row_count=len(run_input.samples),
                raw_capture_available=run_input.raw_capture_available,
                sampling_method=run_input.sampling_method,
            )

        with _step(run_id, "analyze"):
            summary = _analyze(run_input, config.analysis_runner)
        with _step(run_id, "persist_analysis"):
            db.store_analysis(loaded.run_id, summary)
    except _STEP_ERRORS as exc:
        if config.defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
            return _retryable_failure_result(
                run_id=run_id,
                analysis_start=analysis_start,
                exc=exc,
            )
        return _persistence_failure_result(
            run_id=run_id,
            analysis_start=analysis_start,
            exc=exc,
            db=db,
        )

    duration_s = time.monotonic() - analysis_start
    LOGGER.info(
        "Analysis completed for run %s: %d samples in %.2fs",
        loaded.run_id,
        len(run_input.samples),
        duration_s,
        extra=log_extra(
            event="post_analysis_completed",
            run_id=loaded.run_id,
            sample_count=len(run_input.samples),
            duration_s=round(duration_s, 3),
        ),
    )
    return PostAnalysisExecutionSuccess(run_id=loaded.run_id)


# ---------------------------------------------------------------------------
# Step logging and persistence bridge
# ---------------------------------------------------------------------------


@contextmanager
def _step(run_id: str, step_name: str) -> Iterator[JsonObject]:
    """Time one step and log it once on exit.

    The body records ``status`` (default ``ok``) and step details in the yielded
    dict. An exception is logged as ``failed`` and re-raised.
    """
    details: JsonObject = {"status": "ok"}
    step_start = time.monotonic()
    try:
        yield details
    except BaseException as exc:
        details["status"] = "failed"
        details["error_message"] = str(exc)
        raise
    finally:
        status = str(details.pop("status"))
        duration_ms = max(0, int(round((time.monotonic() - step_start) * 1000)))
        log_fn = LOGGER.warning if status in {"degraded", "failed"} else LOGGER.info
        log_fn(
            "Post-analysis step %s for run %s: %s (%d ms)",
            step_name,
            run_id,
            status,
            duration_ms,
            extra=log_extra(
                event="post_analysis_step",
                run_id=run_id,
                step=step_name,
                step_status=status,
                duration_ms=duration_ms,
                details=details,
            ),
        )


def _analyze(
    run_input: PostAnalysisRunInput,
    analysis_runner: PostAnalysisRunner,
) -> PersistedAnalysis:
    raw_summary = analysis_runner(run_input)
    if isinstance(raw_summary, PersistedAnalysis):
        return raw_summary
    return PersistedAnalysis.from_json_object(raw_summary)


# ---------------------------------------------------------------------------
# Failure outcomes
# ---------------------------------------------------------------------------


def _store_load_error(
    *,
    db: HistoryDB,
    run_id: str,
    completed_error: str,
    kind: str,
) -> PostAnalysisExecutionResult:
    try:
        db.store_analysis_error(run_id, completed_error)
    except sqlite3.Error:
        LOGGER.warning(
            "Failed to store analysis error for run %s",
            run_id,
            exc_info=True,
            extra=log_extra(
                event="post_analysis_error_persist_failed",
                run_id=run_id,
            ),
        )
        return PostAnalysisExecutionPersistenceFailure(
            run_id=run_id,
            completed_error=completed_error,
        )

    if kind == "missing_metadata":
        return PostAnalysisExecutionMissingMetadata(
            run_id=run_id,
            completed_error=completed_error,
        )
    return PostAnalysisExecutionNoSamples(
        run_id=run_id,
        completed_error=completed_error,
    )


def _retryable_failure_result(
    *,
    run_id: str,
    analysis_start: float,
    exc: BaseException,
) -> PostAnalysisExecutionRetryableFailure:
    duration_s = time.monotonic() - analysis_start
    LOGGER.warning(
        "Post-analysis attempt failed for run %s after %.2fs; retrying if budget remains: %s",
        run_id,
        duration_s,
        exc,
        exc_info=True,
        extra=log_extra(
            event="post_analysis_retryable_failure",
            run_id=run_id,
            duration_s=round(duration_s, 3),
            error_message=str(exc),
        ),
    )
    return PostAnalysisExecutionRetryableFailure(
        run_id=run_id,
        error_message=str(exc),
        callback_errors=(f"post-analysis failed for run {run_id}: {exc}",),
    )


def _persistence_failure_result(
    *,
    run_id: str,
    analysis_start: float,
    exc: BaseException,
    db: HistoryDB,
) -> PostAnalysisExecutionResult:
    duration_s = time.monotonic() - analysis_start
    callback_error = f"post-analysis failed for run {run_id}: {exc}"
    LOGGER.warning(
        "Analysis failed for run %s after %.2fs: %s",
        run_id,
        duration_s,
        exc,
        exc_info=True,
        extra=log_extra(
            event="post_analysis_failed",
            run_id=run_id,
            duration_s=round(duration_s, 3),
            error_message=str(exc),
        ),
    )
    completed_error = str(exc)
    callback_errors = (callback_error,)

    try:
        db.store_analysis_error(run_id, completed_error)
    except sqlite3.Error as store_exc:
        LOGGER.warning(
            "Failed to store analysis error for run %s",
            run_id,
            exc_info=True,
            extra=log_extra(
                event="post_analysis_error_persist_failed",
                run_id=run_id,
                error_message=str(store_exc),
            ),
        )
        return PostAnalysisExecutionPersistenceFailure(
            run_id=run_id,
            completed_error=completed_error,
            callback_errors=callback_errors
            + (f"history store_analysis_error failed for run {run_id}: {store_exc}",),
        )

    return PostAnalysisExecutionPersistenceFailure(
        run_id=run_id,
        completed_error=completed_error,
        callback_errors=callback_errors,
    )
