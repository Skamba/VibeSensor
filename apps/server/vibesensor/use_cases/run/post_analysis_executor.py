"""Execution and persistence coordination for background post-analysis."""

from __future__ import annotations

import logging
import time
from typing import Protocol

import aiosqlite
from opentelemetry.trace import SpanKind

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.run.post_analysis_input import (
    PostAnalysisRunInput,
    build_post_analysis_input,
)
from vibesensor.use_cases.run.post_analysis_loader import (
    EmptyPostAnalysisSamples,
    MissingPostAnalysisMetadata,
    PostAnalysisLoadResult,
    load_post_analysis_run,
)
from vibesensor.use_cases.run.post_analysis_outcomes import (
    PostAnalysisAttemptResult,
    PostAnalysisExecutionMissingMetadata,
    PostAnalysisExecutionNoSamples,
    PostAnalysisExecutionPersistenceFailure,
    PostAnalysisExecutionResult,
    PostAnalysisExecutionRetryableFailure,
    PostAnalysisExecutionSuccess,
    is_retryable_post_analysis_error,
)

LOGGER = logging.getLogger(__name__)


class PostAnalysisRunner(Protocol):
    """Injected boundary for building the stored post-stop analysis summary."""

    def __call__(self, run: PostAnalysisRunInput) -> PersistedAnalysis: ...


class PostAnalysisLoader(Protocol):
    """Injected boundary for loading metadata and samples for a completed run."""

    def __call__(
        self,
        *,
        run_id: str,
        db: RunPersistence,
    ) -> PostAnalysisLoadResult: ...


def execute_post_analysis(
    *,
    run_id: str,
    db: RunPersistence,
    analysis_runner: PostAnalysisRunner,
    load_run: PostAnalysisLoader = load_post_analysis_run,
    defer_retryable_error_storage: bool = False,
) -> PostAnalysisAttemptResult:
    analysis_start = time.monotonic()
    with start_span(
        __name__,
        "run.post_analysis.execute",
        kind=SpanKind.INTERNAL,
        attributes={"vibesensor.run_id": run_id},
    ) as span:
        LOGGER.info(
            "Analysis started for run %s",
            run_id,
            extra=log_extra(event="post_analysis_started", run_id=run_id),
        )
        try:
            load_result = load_run(run_id=run_id, db=db)
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            mark_span_error(span, exc)
            if defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
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

        if isinstance(load_result, MissingPostAnalysisMetadata):
            span.set_attribute("vibesensor.failure_kind", "missing_metadata")
            LOGGER.warning(
                "Cannot analyse run %s: metadata not found",
                run_id,
                extra=log_extra(
                    event="post_analysis_skipped",
                    run_id=run_id,
                    failure_kind="missing_metadata",
                ),
            )
            return _store_load_error(
                db=db,
                run_id=run_id,
                completed_error=load_result.error_message,
                kind="missing_metadata",
            )

        if isinstance(load_result, EmptyPostAnalysisSamples):
            span.set_attribute("vibesensor.failure_kind", "no_samples")
            LOGGER.warning(
                "Skipping post-analysis for run %s: no samples collected",
                run_id,
                extra=log_extra(
                    event="post_analysis_skipped",
                    run_id=run_id,
                    failure_kind="no_samples",
                ),
            )
            return _store_load_error(
                db=db,
                run_id=run_id,
                completed_error=load_result.error_message,
                kind="no_samples",
            )

        loaded = load_result
        run_input = build_post_analysis_input(loaded)
        span.set_attribute("vibesensor.sample_count", len(run_input.samples))
        try:
            summary = analysis_runner(run_input)
            db.store_analysis(loaded.run_id, summary)
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            mark_span_error(span, exc)
            if defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
                return _retryable_failure_result(
                    run_id=loaded.run_id,
                    analysis_start=analysis_start,
                    exc=exc,
                )
            return _persistence_failure_result(
                run_id=loaded.run_id,
                analysis_start=analysis_start,
                exc=exc,
                db=db,
            )

        duration_s = time.monotonic() - analysis_start
        span.set_attribute("vibesensor.duration_s", round(duration_s, 3))
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


def _store_load_error(
    *,
    db: RunPersistence,
    run_id: str,
    completed_error: str,
    kind: str,
) -> PostAnalysisExecutionResult:
    try:
        db.store_analysis_error(run_id, completed_error)
    except aiosqlite.Error:
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
    db: RunPersistence,
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
    except aiosqlite.Error as store_exc:
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
