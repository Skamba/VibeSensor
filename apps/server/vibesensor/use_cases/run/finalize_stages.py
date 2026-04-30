"""Explicit stage/result helpers for active-run finalization."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.raw_capture import RawCaptureLossStats
from vibesensor.shared.types.run_schema import RunFinalizationStageResult
from vibesensor.use_cases.run.persistence_writer import (
    PersistenceStatusSnapshot,
    RunPersistenceWriter,
)
from vibesensor.use_cases.run.raw_capture_writer import (
    RawCaptureFinalizeResult,
    RunRawCaptureWriter,
)
from vibesensor.use_cases.run.sample_flush import SampleFlushOrchestrator

type FinalizeStageStatus = Literal["ok", "skipped", "degraded", "failed"]

RecordRawCaptureFinalize = Callable[[str, RawCaptureFinalizeResult], None]
RecordFinalizationStages = Callable[[str, str, tuple[RunFinalizationStageResult, ...]], bool]

__all__ = ["ActiveRunFinalizeResult", "FinalizeStageResult", "finalize_active_run"]


@dataclass(frozen=True, slots=True)
class FinalizeStageResult:
    """Structured result for one recorder finalization stage."""

    stage_name: str
    status: FinalizeStageStatus
    duration_ms: int
    artifacts_created: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostic_context: JsonObject = field(default_factory=dict)

    def to_run_metadata_stage(self) -> RunFinalizationStageResult:
        return RunFinalizationStageResult(
            stage_name=self.stage_name,
            status=self.status,
            duration_ms=self.duration_ms,
            artifacts_created=self.artifacts_created,
            warnings=self.warnings,
            diagnostic_context=self.diagnostic_context,
        )


@dataclass(frozen=True, slots=True)
class ActiveRunFinalizeResult:
    """Resolved result of finalizing the currently active run."""

    run_id: str | None
    run_id_to_analyze: str | None
    start_time_utc: str
    end_time_utc: str
    persistence_snapshot: PersistenceStatusSnapshot | None
    stage_results: tuple[FinalizeStageResult, ...]


def _duration_ms(stage_start: float) -> int:
    return max(0, int(round((time.monotonic() - stage_start) * 1000)))


def _make_stage_result(
    *,
    stage_name: str,
    status: FinalizeStageStatus,
    stage_start: float,
    artifacts_created: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    diagnostic_context: JsonObject | None = None,
) -> FinalizeStageResult:
    return FinalizeStageResult(
        stage_name=stage_name,
        status=status,
        duration_ms=_duration_ms(stage_start),
        artifacts_created=artifacts_created,
        warnings=warnings,
        diagnostic_context={} if diagnostic_context is None else diagnostic_context,
    )


def _log_stage_result(
    *,
    logger: logging.Logger,
    run_id: str | None,
    stop_reason: str,
    stage_result: FinalizeStageResult,
) -> None:
    if stage_result.status == "ok":
        return
    log_fn = logger.warning if stage_result.status in {"degraded", "failed"} else logger.info
    log_fn(
        "Run finalize stage %s for run %s is %s",
        stage_result.stage_name,
        run_id or "<none>",
        stage_result.status,
        extra=log_extra(
            event="run_finalize_stage_result",
            run_id=run_id or "",
            stop_reason=stop_reason,
            stage_name=stage_result.stage_name,
            stage_status=stage_result.status,
            duration_ms=stage_result.duration_ms,
            artifacts_created=list(stage_result.artifacts_created),
            warnings=list(stage_result.warnings),
            diagnostic_context=stage_result.diagnostic_context,
        ),
    )


def _log_failed_stage_and_raise(
    *,
    logger: logging.Logger,
    run_id: str | None,
    stop_reason: str,
    stage_name: str,
    stage_start: float,
    exc: BaseException,
    diagnostic_context: JsonObject | None = None,
) -> None:
    failure_result = _make_stage_result(
        stage_name=stage_name,
        status="failed",
        stage_start=stage_start,
        diagnostic_context=(
            {"error_message": str(exc)}
            if diagnostic_context is None
            else {**diagnostic_context, "error_message": str(exc)}
        ),
    )
    _log_stage_result(
        logger=logger,
        run_id=run_id,
        stop_reason=stop_reason,
        stage_result=failure_result,
    )
    raise exc


def _resolve_post_analysis_candidate_stage(
    *,
    run_id: str | None,
    raw_capture_finalize_status: str | None,
    persistence: RunPersistenceWriter,
    persistence_snapshot: PersistenceStatusSnapshot | None,
    persistence_finalized: bool,
) -> tuple[str | None, FinalizeStageResult]:
    resolve_stage_start = time.monotonic()
    run_id_to_analyze: str | None = None
    if run_id is None:
        resolve_reason = "no_active_run"
    elif raw_capture_finalize_status == "timeout":
        resolve_reason = "raw_capture_finalize_unsettled"
    elif not persistence_finalized:
        resolve_reason = "persistence_finalize_unsettled"
    else:
        run_id_to_analyze = persistence.ready_for_analysis(run_id)
        resolve_reason = "ready" if run_id_to_analyze else "history_not_ready"
    return run_id_to_analyze, _make_stage_result(
        stage_name="ResolvePostAnalysisCandidateStage",
        status="ok" if run_id_to_analyze else "skipped",
        stage_start=resolve_stage_start,
        artifacts_created=("post_analysis_candidate",) if run_id_to_analyze else (),
        diagnostic_context={
            "run_id": run_id or "",
            "reason": resolve_reason,
            "history_run_created": persistence.history_run_created,
            "written_sample_count": (
                0 if persistence_snapshot is None else persistence_snapshot.written_sample_count
            ),
            "raw_capture_status": raw_capture_finalize_status,
            "persistence_finalized": persistence_finalized,
        },
    )


def _persist_finalization_stage_results(
    *,
    run_id: str | None,
    start_time_utc: str,
    stop_reason: str,
    stage_results: list[FinalizeStageResult],
    record_finalization_stage_results: RecordFinalizationStages | None,
    logger: logging.Logger,
) -> None:
    if run_id is None or record_finalization_stage_results is None:
        return
    metadata_stage_results = tuple(stage.to_run_metadata_stage() for stage in stage_results)
    if record_finalization_stage_results(run_id, start_time_utc, metadata_stage_results):
        return
    logger.warning(
        "run_finalize_stage_results_persist_failed",
        extra=log_extra(
            event="run_finalize_stage_results_persist_failed",
            run_id=run_id,
            stop_reason=stop_reason,
            stage_count=len(metadata_stage_results),
        ),
    )


def finalize_active_run(
    *,
    run_id: str | None,
    start_time_utc: str | None,
    stop_reason: str,
    ingest_drop_losses: Mapping[str, RawCaptureLossStats] | None,
    sample_flush: SampleFlushOrchestrator,
    persistence: RunPersistenceWriter,
    raw_capture: RunRawCaptureWriter,
    record_raw_capture_finalize_result: RecordRawCaptureFinalize,
    record_finalization_stage_results: RecordFinalizationStages | None = None,
    logger: logging.Logger,
) -> ActiveRunFinalizeResult:
    stage_results: list[FinalizeStageResult] = []

    flush_stage_start = time.monotonic()
    flush_snapshot = sample_flush.pending_flush_snapshot()
    if flush_snapshot is None:
        flush_stage = _make_stage_result(
            stage_name="FlushPendingRowsStage",
            status="skipped",
            stage_start=flush_stage_start,
            diagnostic_context={"reason": "no_pending_flush"},
        )
    else:
        try:
            sample_flush.append_records(
                flush_snapshot.run_id,
                flush_snapshot.start_time_utc,
                flush_snapshot.start_mono_s,
                refresh_metrics=True,
            )
        except BaseException as exc:
            _log_failed_stage_and_raise(
                logger=logger,
                run_id=run_id,
                stop_reason=stop_reason,
                stage_name="FlushPendingRowsStage",
                stage_start=flush_stage_start,
                exc=exc,
                diagnostic_context={"run_id": flush_snapshot.run_id},
            )
        flush_stage = _make_stage_result(
            stage_name="FlushPendingRowsStage",
            status="ok",
            stage_start=flush_stage_start,
            artifacts_created=("pending_rows_flushed",),
            diagnostic_context={"run_id": flush_snapshot.run_id},
        )
    stage_results.append(flush_stage)
    _log_stage_result(
        logger=logger,
        run_id=run_id,
        stop_reason=stop_reason,
        stage_result=flush_stage,
    )

    resolved_start_time_utc = start_time_utc or utc_now_iso()
    resolved_end_time_utc = utc_now_iso()
    persistence_snapshot = persistence.status_snapshot() if run_id is not None else None
    raw_capture_finalize_status: str | None = None

    raw_capture_stage_start = time.monotonic()
    if run_id is None:
        raw_capture_stage = _make_stage_result(
            stage_name="FinalizeRawCaptureStage",
            status="skipped",
            stage_start=raw_capture_stage_start,
            diagnostic_context={"reason": "no_active_run"},
        )
    else:
        try:
            finalize_result = raw_capture.finalize_run(
                run_id,
                sensor_losses=ingest_drop_losses,
            )
        except BaseException as exc:
            _log_failed_stage_and_raise(
                logger=logger,
                run_id=run_id,
                stop_reason=stop_reason,
                stage_name="FinalizeRawCaptureStage",
                stage_start=raw_capture_stage_start,
                exc=exc,
                diagnostic_context={"run_id": run_id},
            )
        record_raw_capture_finalize_result(run_id, finalize_result)
        raw_capture_finalize_status = finalize_result.status
        raw_capture_status: FinalizeStageStatus
        raw_capture_warnings: tuple[str, ...] = ()
        raw_capture_artifacts: tuple[str, ...] = ()
        if finalize_result.status == "completed":
            raw_capture_status = "ok"
            if finalize_result.manifest is not None:
                raw_capture_artifacts = ("raw_capture_manifest",)
        elif finalize_result.status == "not_configured":
            raw_capture_status = "skipped"
        else:
            raw_capture_status = "degraded"
            raw_capture_warnings = (finalize_result.error or finalize_result.status,)
        raw_capture_stage = _make_stage_result(
            stage_name="FinalizeRawCaptureStage",
            status=raw_capture_status,
            stage_start=raw_capture_stage_start,
            artifacts_created=raw_capture_artifacts,
            warnings=raw_capture_warnings,
            diagnostic_context={
                "run_id": run_id,
                "raw_capture_status": finalize_result.status,
                "queue_depth": finalize_result.queue_depth,
                "sensor_loss_count": len(ingest_drop_losses or {}),
            },
        )
    stage_results.append(raw_capture_stage)
    _log_stage_result(
        logger=logger,
        run_id=run_id,
        stop_reason=stop_reason,
        stage_result=raw_capture_stage,
    )

    persistence_stage_start = time.monotonic()
    persistence_finalized = False
    if run_id is None:
        persistence_stage = _make_stage_result(
            stage_name="FinalizePersistenceStage",
            status="skipped",
            stage_start=persistence_stage_start,
            diagnostic_context={"reason": "no_active_run"},
        )
    else:
        try:
            persistence_finalized = persistence.finalize_run(
                run_id,
                resolved_start_time_utc,
                resolved_end_time_utc,
            )
        except BaseException as exc:
            _log_failed_stage_and_raise(
                logger=logger,
                run_id=run_id,
                stop_reason=stop_reason,
                stage_name="FinalizePersistenceStage",
                stage_start=persistence_stage_start,
                exc=exc,
                diagnostic_context={"run_id": run_id},
            )
        persistence_stage = _make_stage_result(
            stage_name="FinalizePersistenceStage",
            status="ok" if persistence_finalized else "degraded",
            stage_start=persistence_stage_start,
            artifacts_created=("history_run_finalized",) if persistence_finalized else (),
            warnings=() if persistence_finalized else ("history_finalize_failed",),
            diagnostic_context={
                "run_id": run_id,
                "raw_capture_status": raw_capture_finalize_status,
            },
        )
    stage_results.append(persistence_stage)
    _log_stage_result(
        logger=logger,
        run_id=run_id,
        stop_reason=stop_reason,
        stage_result=persistence_stage,
    )

    run_id_to_analyze, resolve_stage = _resolve_post_analysis_candidate_stage(
        run_id=run_id,
        raw_capture_finalize_status=raw_capture_finalize_status,
        persistence=persistence,
        persistence_snapshot=persistence_snapshot,
        persistence_finalized=persistence_finalized,
    )
    stage_results.append(resolve_stage)
    _log_stage_result(
        logger=logger,
        run_id=run_id,
        stop_reason=stop_reason,
        stage_result=resolve_stage,
    )
    _persist_finalization_stage_results(
        run_id=run_id,
        start_time_utc=resolved_start_time_utc,
        stop_reason=stop_reason,
        stage_results=stage_results,
        record_finalization_stage_results=record_finalization_stage_results,
        logger=logger,
    )

    return ActiveRunFinalizeResult(
        run_id=run_id,
        run_id_to_analyze=run_id_to_analyze,
        start_time_utc=resolved_start_time_utc,
        end_time_utc=resolved_end_time_utc,
        persistence_snapshot=persistence_snapshot,
        stage_results=tuple(stage_results),
    )
