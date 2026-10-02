"""Active-run finalization: flush, close raw capture and history, pick the run to analyse."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.raw_capture import RawCaptureLossStats
from vibesensor.shared.types.run_schema import (
    RunFinalizationStageResult,
    RunFinalizationStageStatus,
)
from vibesensor.use_cases.run.persistence_writer import (
    PersistenceStatusSnapshot,
    RunPersistenceWriter,
)
from vibesensor.use_cases.run.raw_capture_writer import (
    RawCaptureFinalizeResult,
    RunRawCaptureWriter,
)
from vibesensor.use_cases.run.sample_flush import SampleFlushOrchestrator

RecordRawCaptureFinalize = Callable[[str, RawCaptureFinalizeResult], object]
RecordFinalizationStages = Callable[[str, str, tuple[RunFinalizationStageResult, ...]], bool]

__all__ = ["ActiveRunFinalizeResult", "finalize_active_run"]


@dataclass(frozen=True, slots=True)
class ActiveRunFinalizeResult:
    """Resolved result of finalizing the currently active run."""

    run_id: str | None
    run_id_to_analyze: str | None
    start_time_utc: str
    end_time_utc: str
    persistence_snapshot: PersistenceStatusSnapshot | None
    stage_results: tuple[RunFinalizationStageResult, ...]


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
    """Flush, finalize raw capture and history, then pick the run to analyse.

    Each step is recorded as a ``RunFinalizationStageResult`` (persisted into the
    run metadata, where report/history fallback reasons read it) and logged once
    as a ``run_finalize_stage_result`` event. A step that raises is logged as
    ``failed`` and the exception propagates.
    """
    stages: list[RunFinalizationStageResult] = []

    def record(
        stage_name: str,
        stage_start: float,
        status: RunFinalizationStageStatus,
        *,
        artifacts_created: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        diagnostic_context: JsonObject | None = None,
    ) -> None:
        stage = RunFinalizationStageResult(
            stage_name=stage_name,
            status=status,
            duration_ms=max(0, int(round((time.monotonic() - stage_start) * 1000))),
            artifacts_created=artifacts_created,
            warnings=warnings,
            diagnostic_context={} if diagnostic_context is None else diagnostic_context,
        )
        stages.append(stage)
        log_fn = logger.warning if status in {"degraded", "failed"} else logger.info
        log_fn(
            "Run finalize stage %s for run %s is %s",
            stage_name,
            run_id or "<none>",
            status,
            extra=log_extra(
                event="run_finalize_stage_result",
                run_id=run_id or "",
                stop_reason=stop_reason,
                stage_name=stage_name,
                stage_status=status,
                duration_ms=stage.duration_ms,
                artifacts_created=list(artifacts_created),
                warnings=list(warnings),
                diagnostic_context=stage.diagnostic_context,
            ),
        )

    # 1. Flush rows still buffered for the active run.
    stage_start = time.monotonic()
    flush_snapshot = sample_flush.pending_flush_snapshot()
    if flush_snapshot is None:
        record(
            "FlushPendingRowsStage",
            stage_start,
            "skipped",
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
            record(
                "FlushPendingRowsStage",
                stage_start,
                "failed",
                diagnostic_context={"run_id": flush_snapshot.run_id, "error_message": str(exc)},
            )
            raise
        record(
            "FlushPendingRowsStage",
            stage_start,
            "ok",
            artifacts_created=("pending_rows_flushed",),
            diagnostic_context={"run_id": flush_snapshot.run_id},
        )

    resolved_start_time_utc = start_time_utc or utc_now_iso()
    resolved_end_time_utc = utc_now_iso()
    persistence_snapshot = persistence.status_snapshot() if run_id is not None else None

    # 2. Close the raw-capture sidecar.
    raw_capture_finalize_status: str | None = None
    stage_start = time.monotonic()
    if run_id is None:
        record(
            "FinalizeRawCaptureStage",
            stage_start,
            "skipped",
            diagnostic_context={"reason": "no_active_run"},
        )
    else:
        try:
            finalize_result = raw_capture.finalize_run(run_id, sensor_losses=ingest_drop_losses)
        except BaseException as exc:
            record(
                "FinalizeRawCaptureStage",
                stage_start,
                "failed",
                diagnostic_context={"run_id": run_id, "error_message": str(exc)},
            )
            raise
        record_raw_capture_finalize_result(run_id, finalize_result)
        raw_capture_finalize_status = finalize_result.status
        raw_capture_stage_status: RunFinalizationStageStatus = "degraded"
        if finalize_result.status == "completed":
            raw_capture_stage_status = "ok"
        elif finalize_result.status == "not_configured":
            raw_capture_stage_status = "skipped"
        record(
            "FinalizeRawCaptureStage",
            stage_start,
            raw_capture_stage_status,
            artifacts_created=(
                ("raw_capture_manifest",)
                if finalize_result.status == "completed" and finalize_result.manifest is not None
                else ()
            ),
            warnings=(
                (finalize_result.error or finalize_result.status,)
                if raw_capture_stage_status == "degraded"
                else ()
            ),
            diagnostic_context={
                "run_id": run_id,
                "raw_capture_status": finalize_result.status,
                "queue_depth": finalize_result.queue_depth,
                "sensor_loss_count": len(ingest_drop_losses or {}),
            },
        )

    # 3. Mark the history run finished.
    persistence_finalized = False
    stage_start = time.monotonic()
    if run_id is None:
        record(
            "FinalizePersistenceStage",
            stage_start,
            "skipped",
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
            record(
                "FinalizePersistenceStage",
                stage_start,
                "failed",
                diagnostic_context={"run_id": run_id, "error_message": str(exc)},
            )
            raise
        record(
            "FinalizePersistenceStage",
            stage_start,
            "ok" if persistence_finalized else "degraded",
            artifacts_created=("history_run_finalized",) if persistence_finalized else (),
            warnings=() if persistence_finalized else ("history_finalize_failed",),
            diagnostic_context={
                "run_id": run_id,
                "raw_capture_status": raw_capture_finalize_status,
            },
        )

    # 4. Decide whether the run can be queued for post-analysis.
    stage_start = time.monotonic()
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
    record(
        "ResolvePostAnalysisCandidateStage",
        stage_start,
        "ok" if run_id_to_analyze else "skipped",
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

    if (
        run_id is not None
        and record_finalization_stage_results is not None
        and not record_finalization_stage_results(run_id, resolved_start_time_utc, tuple(stages))
    ):
        logger.warning(
            "run_finalize_stage_results_persist_failed",
            extra=log_extra(
                event="run_finalize_stage_results_persist_failed",
                run_id=run_id,
                stop_reason=stop_reason,
                stage_count=len(stages),
            ),
        )

    return ActiveRunFinalizeResult(
        run_id=run_id,
        run_id_to_analyze=run_id_to_analyze,
        start_time_utc=resolved_start_time_utc,
        end_time_utc=resolved_end_time_utc,
        persistence_snapshot=persistence_snapshot,
        stage_results=tuple(stages),
    )
