"""Execution and persistence outcomes for background post-analysis."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.run.post_analysis_loader import (
    EmptyPostAnalysisSamples,
    MissingPostAnalysisMetadata,
    PostAnalysisLoadResult,
    load_post_analysis_run,
)

LOGGER = logging.getLogger(__name__)


class PostAnalysisRunner(Protocol):
    """Injected boundary for building the stored post-stop analysis summary."""

    def __call__(
        self,
        *,
        run_id: str,
        metadata: RunMetadata,
        samples: list[SensorFrame],
        language: str,
        total_sample_count: int,
        stride: int,
    ) -> PersistedAnalysis: ...


class PostAnalysisLoader(Protocol):
    def __call__(
        self,
        *,
        run_id: str,
        db: RunPersistence,
    ) -> PostAnalysisLoadResult: ...


@dataclass(frozen=True, slots=True)
class PostAnalysisExecutionSuccess:
    run_id: str


@dataclass(frozen=True, slots=True)
class PostAnalysisExecutionMissingMetadata:
    run_id: str
    completed_error: str


@dataclass(frozen=True, slots=True)
class PostAnalysisExecutionNoSamples:
    run_id: str
    completed_error: str


@dataclass(frozen=True, slots=True)
class PostAnalysisExecutionAnalysisFailure:
    run_id: str
    completed_error: str
    callback_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PostAnalysisExecutionPersistenceFailure:
    run_id: str
    completed_error: str
    callback_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PostAnalysisExecutionRetryableFailure:
    run_id: str
    error_message: str
    callback_errors: tuple[str, ...] = ()


PostAnalysisExecutionResult = (
    PostAnalysisExecutionSuccess
    | PostAnalysisExecutionMissingMetadata
    | PostAnalysisExecutionNoSamples
    | PostAnalysisExecutionAnalysisFailure
    | PostAnalysisExecutionPersistenceFailure
)

PostAnalysisAttemptResult = PostAnalysisExecutionResult | PostAnalysisExecutionRetryableFailure


def is_retryable_post_analysis_error(exc: Exception) -> bool:
    return isinstance(exc, (sqlite3.Error, OSError, MemoryError))


def execute_post_analysis(
    *,
    run_id: str,
    db: RunPersistence,
    analysis_runner: PostAnalysisRunner,
    load_run: PostAnalysisLoader = load_post_analysis_run,
    defer_retryable_error_storage: bool = False,
) -> PostAnalysisAttemptResult:
    analysis_start = time.monotonic()
    LOGGER.info("Analysis started for run %s", run_id)
    try:
        load_result = load_run(run_id=run_id, db=db)
    except Exception as exc:  # includes sample-read and metadata-read failures
        if defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
            return _retryable_failure_result(
                run_id=run_id,
                analysis_start=analysis_start,
                exc=exc,
            )
        return _failure_result(
            run_id=run_id,
            analysis_start=analysis_start,
            exc=exc,
            db=db,
            kind="persistence" if isinstance(exc, sqlite3.Error) else "analysis",
        )

    if isinstance(load_result, MissingPostAnalysisMetadata):
        LOGGER.warning("Cannot analyse run %s: metadata not found", run_id)
        return _store_load_error(
            db=db,
            run_id=run_id,
            completed_error=load_result.error_message,
            kind="missing_metadata",
        )

    if isinstance(load_result, EmptyPostAnalysisSamples):
        LOGGER.warning("Skipping post-analysis for run %s: no samples collected", run_id)
        return _store_load_error(
            db=db,
            run_id=run_id,
            completed_error=load_result.error_message,
            kind="no_samples",
        )

    loaded = load_result
    try:
        summary = analysis_runner(
            run_id=loaded.run_id,
            metadata=loaded.metadata,
            samples=loaded.samples,
            language=loaded.language,
            total_sample_count=loaded.total_sample_count,
            stride=loaded.stride,
        )
        db.store_analysis(loaded.run_id, summary)
    except Exception as exc:
        if defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
            return _retryable_failure_result(
                run_id=loaded.run_id,
                analysis_start=analysis_start,
                exc=exc,
            )
        return _failure_result(
            run_id=loaded.run_id,
            analysis_start=analysis_start,
            exc=exc,
            db=db,
            kind="persistence" if isinstance(exc, sqlite3.Error) else "analysis",
        )

    duration_s = time.monotonic() - analysis_start
    LOGGER.info(
        "Analysis completed for run %s: %d samples in %.2fs",
        loaded.run_id,
        len(loaded.samples),
        duration_s,
    )
    return PostAnalysisExecutionSuccess(run_id=loaded.run_id)


def _store_load_error(
    *,
    db: RunPersistence,
    run_id: str,
    completed_error: str,
    kind: Literal["missing_metadata", "no_samples"],
) -> PostAnalysisExecutionResult:
    try:
        db.store_analysis_error(run_id, completed_error)
    except sqlite3.Error:
        LOGGER.warning("Failed to store analysis error for run %s", run_id, exc_info=True)
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
    exc: Exception,
) -> PostAnalysisExecutionRetryableFailure:
    duration_s = time.monotonic() - analysis_start
    LOGGER.warning(
        "Post-analysis attempt failed for run %s after %.2fs; retrying if budget remains: %s",
        run_id,
        duration_s,
        exc,
        exc_info=True,
    )
    return PostAnalysisExecutionRetryableFailure(
        run_id=run_id,
        error_message=str(exc),
        callback_errors=(f"post-analysis failed for run {run_id}: {exc}",),
    )


def _failure_result(
    *,
    run_id: str,
    analysis_start: float,
    exc: Exception,
    db: RunPersistence,
    kind: Literal["analysis", "persistence"],
) -> PostAnalysisExecutionResult:
    duration_s = time.monotonic() - analysis_start
    callback_error = f"post-analysis failed for run {run_id}: {exc}"
    LOGGER.warning(
        "Analysis failed for run %s after %.2fs: %s",
        run_id,
        duration_s,
        exc,
        exc_info=True,
    )
    completed_error = str(exc)
    callback_errors = (callback_error,)

    try:
        db.store_analysis_error(run_id, completed_error)
    except sqlite3.Error as store_exc:
        LOGGER.warning("Failed to store analysis error for run %s", run_id, exc_info=True)
        return PostAnalysisExecutionPersistenceFailure(
            run_id=run_id,
            completed_error=completed_error,
            callback_errors=callback_errors
            + (f"history store_analysis_error failed for run {run_id}: {store_exc}",),
        )

    if kind == "analysis":
        return PostAnalysisExecutionAnalysisFailure(
            run_id=run_id,
            completed_error=completed_error,
            callback_errors=callback_errors,
        )
    return PostAnalysisExecutionPersistenceFailure(
        run_id=run_id,
        completed_error=completed_error,
        callback_errors=callback_errors,
    )
