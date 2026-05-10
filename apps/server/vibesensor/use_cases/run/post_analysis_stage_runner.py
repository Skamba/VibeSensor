"""Shared stage result and persistence-call helpers for post-analysis."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn

from vibesensor.shared.types.json_types import JsonObject

type PostAnalysisStageStatus = Literal["ok", "skipped", "degraded", "failed"]


@dataclass(frozen=True, slots=True)
class PostAnalysisStageResult:
    """Structured result for one executor pipeline stage."""

    stage_name: str
    status: PostAnalysisStageStatus
    duration_ms: int
    artifacts_created: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostic_context: JsonObject = field(default_factory=dict)


class PostAnalysisStageFailure(Exception):
    """Retryable or persistence-bound stage failure with explicit stage metadata."""

    def __init__(self, stage_result: PostAnalysisStageResult, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.stage_result = stage_result
        self.cause = cause


def sync_run_persistence_call(db: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Invoke ``db.<method_name>`` synchronously from a worker thread."""
    method = getattr(db, method_name)
    result = method(*args, **kwargs)
    if asyncio.iscoroutine(result):
        runner = getattr(db, "_run_on_engine_loop", None)
        if callable(runner):
            return runner(result)
        return asyncio.run(result)
    return result


def make_stage_result(
    *,
    stage_name: str,
    status: PostAnalysisStageStatus,
    stage_start: float,
    artifacts_created: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    diagnostic_context: JsonObject | None = None,
) -> PostAnalysisStageResult:
    return PostAnalysisStageResult(
        stage_name=stage_name,
        status=status,
        duration_ms=max(0, int(round((time.monotonic() - stage_start) * 1000))),
        artifacts_created=artifacts_created,
        warnings=warnings,
        diagnostic_context={} if diagnostic_context is None else diagnostic_context,
    )


def warning_codes(warnings: tuple[object, ...]) -> tuple[str, ...]:
    codes: list[str] = []
    for warning in warnings:
        code = getattr(warning, "code", None)
        if isinstance(code, str) and code:
            codes.append(code)
    return tuple(codes)


def raise_stage_failure(
    *,
    stage_name: str,
    stage_start: float,
    exc: BaseException,
    diagnostic_context: JsonObject | None = None,
) -> NoReturn:
    raise PostAnalysisStageFailure(
        make_stage_result(
            stage_name=stage_name,
            status="failed",
            stage_start=stage_start,
            diagnostic_context=(
                {"error_message": str(exc)}
                if diagnostic_context is None
                else {**diagnostic_context, "error_message": str(exc)}
            ),
        ),
        exc,
    ) from exc
