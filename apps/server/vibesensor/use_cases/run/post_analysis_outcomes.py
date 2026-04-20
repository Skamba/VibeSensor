"""Explicit post-analysis execution outcomes and retry classification."""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

__all__ = [
    "PostAnalysisAttemptResult",
    "PostAnalysisExecutionMissingMetadata",
    "PostAnalysisExecutionNoSamples",
    "PostAnalysisExecutionPersistenceFailure",
    "PostAnalysisExecutionResult",
    "PostAnalysisExecutionRetryableFailure",
    "PostAnalysisExecutionSuccess",
    "execution_callback_errors",
    "is_retryable_post_analysis_error",
]


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
    | PostAnalysisExecutionPersistenceFailure
)

PostAnalysisAttemptResult = PostAnalysisExecutionResult | PostAnalysisExecutionRetryableFailure


def is_retryable_post_analysis_error(exc: BaseException) -> bool:
    """Return whether a post-analysis boundary failure should be retried."""

    return isinstance(exc, (aiosqlite.Error, OSError, MemoryError))


def execution_callback_errors(result: PostAnalysisExecutionResult) -> tuple[str, ...]:
    if isinstance(result, PostAnalysisExecutionPersistenceFailure):
        return result.callback_errors
    return ()
