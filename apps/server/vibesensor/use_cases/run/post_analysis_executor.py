"""Execution and persistence coordination for background post-analysis."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
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
    LoadedPostAnalysisRun,
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
from vibesensor.use_cases.run.post_analysis_stage_runner import (
    PostAnalysisStageFailure,
    PostAnalysisStageResult,
    make_stage_result,
    raise_stage_failure,
    sync_run_persistence_call,
    warning_codes,
)
from vibesensor.use_cases.run.post_analysis_whole_run_pipeline import (
    WholeRunArtifactBuilder,
    WholeRunContextBuilder,
    WholeRunDiagnosisSummaryBuilder,
    WholeRunOrderFamilySummaryBuilder,
    WholeRunOrderTraceBuilder,
    WholeRunOrderTraceSummaryBuilder,
    WholeRunPipelineStageOutput,
    WholeRunSpatialCoherenceBuilder,
    resolve_whole_run_builders,
    run_whole_run_pipeline_stages,
)
from vibesensor.use_cases.run.post_analysis_whole_run_projection import (
    append_run_context_warnings,
    append_whole_run_analysis_metadata,
    append_whole_run_context,
    append_whole_run_diagnosis_summaries,
    append_whole_run_diagnosis_summary_metadata,
    append_whole_run_order_family_summary_metadata,
    append_whole_run_order_summaries,
    append_whole_run_order_trace_metadata,
    append_whole_run_order_trace_summary_metadata,
    append_whole_run_spatial_coherence_metadata,
    append_whole_run_spatial_summaries,
    append_whole_run_spectral_metadata,
    ranked_whole_run_order_summaries,
    ranked_whole_run_spatial_summaries,
    refresh_report_fallback_metadata,
)

LOGGER = logging.getLogger(__name__)


def _coerce_persisted_analysis(
    summary: PersistedAnalysis | Mapping[str, object],
) -> PersistedAnalysis:
    if isinstance(summary, PersistedAnalysis):
        return summary
    return PersistedAnalysis.from_json_object(summary)


class PostAnalysisRunner(Protocol):
    """Injected boundary for building the stored post-stop analysis summary."""

    def __call__(self, run: PostAnalysisRunInput) -> PersistedAnalysis | Mapping[str, object]: ...


class PostAnalysisLoader(Protocol):
    """Injected boundary for loading metadata and samples for a completed run."""

    def __call__(
        self,
        *,
        run_id: str,
        db: RunPersistence,
    ) -> PostAnalysisLoadResult: ...


@dataclass(frozen=True, slots=True)
class PostAnalysisLoadStageOutput:
    """Output of the load stage before input shaping begins."""

    stage_result: PostAnalysisStageResult
    loaded: LoadedPostAnalysisRun | None = None
    terminal_result: PostAnalysisAttemptResult | None = None


@dataclass(frozen=True, slots=True)
class PostAnalysisInputStageOutput:
    """Output of canonical post-analysis input shaping."""

    run_input: PostAnalysisRunInput
    stage_result: PostAnalysisStageResult


def _log_stage_result(run_id: str, stage_result: PostAnalysisStageResult) -> None:
    if stage_result.status == "ok":
        return
    log_fn = LOGGER.warning if stage_result.status in {"degraded", "failed"} else LOGGER.info
    log_fn(
        "Post-analysis stage %s for run %s is %s",
        stage_result.stage_name,
        run_id,
        stage_result.status,
        extra=log_extra(
            event="post_analysis_stage_result",
            run_id=run_id,
            stage_name=stage_result.stage_name,
            stage_status=stage_result.status,
            duration_ms=stage_result.duration_ms,
            artifacts_created=list(stage_result.artifacts_created),
            warnings=list(stage_result.warnings),
            diagnostic_context=stage_result.diagnostic_context,
        ),
    )


def run_load_run_stage(
    *,
    run_id: str,
    db: RunPersistence,
    load_run: PostAnalysisLoader,
    analysis_start: float,
    defer_retryable_error_storage: bool,
) -> PostAnalysisLoadStageOutput:
    stage_name = "LoadRunStage"
    stage_start = time.monotonic()
    try:
        load_result = load_run(run_id=run_id, db=db)
    except (aiosqlite.Error, OSError, MemoryError) as exc:
        terminal_result: PostAnalysisAttemptResult
        if defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
            terminal_result = _retryable_failure_result(
                run_id=run_id,
                analysis_start=analysis_start,
                exc=exc,
                stage_name=stage_name,
            )
        else:
            terminal_result = _persistence_failure_result(
                run_id=run_id,
                analysis_start=analysis_start,
                exc=exc,
                db=db,
                stage_name=stage_name,
            )
        return PostAnalysisLoadStageOutput(
            stage_result=make_stage_result(
                stage_name=stage_name,
                status="failed",
                stage_start=stage_start,
                diagnostic_context={"error_message": str(exc)},
            ),
            terminal_result=terminal_result,
        )

    if isinstance(load_result, MissingPostAnalysisMetadata):
        LOGGER.warning(
            "Cannot analyse run %s: metadata not found",
            run_id,
            extra=log_extra(
                event="post_analysis_skipped",
                run_id=run_id,
                failure_kind="missing_metadata",
            ),
        )
        return PostAnalysisLoadStageOutput(
            stage_result=make_stage_result(
                stage_name=stage_name,
                status="failed",
                stage_start=stage_start,
                diagnostic_context={"failure_kind": "missing_metadata"},
            ),
            terminal_result=_store_load_error(
                db=db,
                run_id=run_id,
                completed_error=load_result.error_message,
                kind="missing_metadata",
            ),
        )

    if isinstance(load_result, EmptyPostAnalysisSamples):
        LOGGER.warning(
            "Skipping post-analysis for run %s: no samples collected",
            run_id,
            extra=log_extra(
                event="post_analysis_skipped",
                run_id=run_id,
                failure_kind="no_samples",
            ),
        )
        return PostAnalysisLoadStageOutput(
            stage_result=make_stage_result(
                stage_name=stage_name,
                status="failed",
                stage_start=stage_start,
                diagnostic_context={"failure_kind": "no_samples"},
            ),
            terminal_result=_store_load_error(
                db=db,
                run_id=run_id,
                completed_error=load_result.error_message,
                kind="no_samples",
            ),
        )

    return PostAnalysisLoadStageOutput(
        stage_result=make_stage_result(
            stage_name=stage_name,
            status="ok",
            stage_start=stage_start,
            diagnostic_context={
                "sample_count": len(load_result.samples),
                "raw_capture_available": load_result.raw_capture is not None,
                "raw_capture_manifest_available": load_result.raw_capture_manifest is not None,
            },
        ),
        loaded=load_result,
    )


def run_build_post_analysis_input_stage(
    loaded: LoadedPostAnalysisRun,
) -> PostAnalysisInputStageOutput:
    stage_name = "BuildPostAnalysisInputStage"
    stage_start = time.monotonic()
    try:
        run_input = build_post_analysis_input(loaded)
    except (aiosqlite.Error, OSError, MemoryError) as exc:
        raise_stage_failure(
            stage_name=stage_name,
            stage_start=stage_start,
            exc=exc,
            diagnostic_context={"run_id": loaded.run_id},
        )
    return PostAnalysisInputStageOutput(
        run_input=run_input,
        stage_result=make_stage_result(
            stage_name=stage_name,
            status="ok",
            stage_start=stage_start,
            diagnostic_context={
                "summary_row_count": len(run_input.samples),
                "raw_capture_available": run_input.raw_capture_available,
                "sampling_method": run_input.sampling_method,
            },
        ),
    )


def run_build_report_facts_stage(
    *,
    run_input: PostAnalysisRunInput,
    analysis_runner: PostAnalysisRunner,
    whole_run_output: WholeRunPipelineStageOutput,
    diagnosis_summary_builder: WholeRunDiagnosisSummaryBuilder,
) -> tuple[PersistedAnalysis, PostAnalysisStageResult]:
    stage_name = "BuildReportFactsStage"
    stage_start = time.monotonic()
    try:
        summary = _coerce_persisted_analysis(analysis_runner(run_input))
    except (aiosqlite.Error, OSError, MemoryError) as exc:
        raise_stage_failure(
            stage_name=stage_name,
            stage_start=stage_start,
            exc=exc,
            diagnostic_context={"run_id": run_input.run_id},
        )

    spectral_result = whole_run_output.spectral_result
    spectral_bundle = whole_run_output.spectral_bundle
    context_bundle = whole_run_output.context_bundle
    order_trace_bundle = whole_run_output.order_trace_bundle
    order_trace_summary_bundle = whole_run_output.order_trace_summary_bundle
    order_family_summary_bundle = whole_run_output.order_family_summary_bundle
    spatial_coherence_bundle = whole_run_output.spatial_coherence_bundle
    stored_artifact_manifest = whole_run_output.stored_artifact_manifest

    if spectral_result is not None:
        summary = append_whole_run_spectral_metadata(
            summary,
            spectral_result.coverage_summary,
            spectral_bundle=spectral_bundle,
        )
        summary = append_run_context_warnings(summary, spectral_result.coverage_summary.warnings)
    if context_bundle is not None:
        summary = append_whole_run_context(summary, context_bundle)

    analysis_payload = summary.to_json_object()
    analysis_metadata_payload = analysis_payload.get("analysis_metadata")
    analysis_metadata = (
        dict(analysis_metadata_payload) if isinstance(analysis_metadata_payload, dict) else {}
    )

    if order_trace_bundle is not None:
        summary = append_whole_run_order_trace_metadata(summary, order_trace_bundle)
    if order_trace_summary_bundle is not None:
        summary = append_whole_run_order_trace_summary_metadata(
            summary,
            order_trace_summary_bundle,
        )
    if order_family_summary_bundle is not None:
        summary = append_whole_run_order_summaries(summary, order_family_summary_bundle)
        summary = append_whole_run_order_family_summary_metadata(
            summary,
            order_family_summary_bundle,
        )
    if spatial_coherence_bundle is not None:
        summary = append_whole_run_spatial_summaries(summary, spatial_coherence_bundle)
        summary = append_whole_run_spatial_coherence_metadata(
            summary,
            spatial_coherence_bundle,
        )
    if context_bundle is not None and order_family_summary_bundle is not None:
        diagnosis_summaries = diagnosis_summary_builder(
            analysis_metadata=analysis_metadata,
            context_bundle=context_bundle,
            order_summaries=ranked_whole_run_order_summaries(order_family_summary_bundle.summaries),
            spatial_summaries=(
                ranked_whole_run_spatial_summaries(spatial_coherence_bundle.summaries)
                if spatial_coherence_bundle is not None
                else ()
            ),
            car_order_reference_status=(
                run_input.context.car.order_reference_status
                if run_input.context.car is not None
                else None
            ),
        )
        if diagnosis_summaries:
            summary = append_whole_run_diagnosis_summaries(summary, diagnosis_summaries)
            summary = append_whole_run_diagnosis_summary_metadata(
                summary,
                diagnosis_summaries,
            )
    if stored_artifact_manifest is not None:
        summary = append_whole_run_analysis_metadata(summary, stored_artifact_manifest)

    return refresh_report_fallback_metadata(summary), make_stage_result(
        stage_name=stage_name,
        status="ok",
        stage_start=stage_start,
        warnings=(
            warning_codes(tuple(spectral_result.coverage_summary.warnings))
            if spectral_result is not None
            else ()
        ),
        diagnostic_context={
            "whole_run_artifacts_available": stored_artifact_manifest is not None,
            "whole_run_context_available": context_bundle is not None,
            "whole_run_order_family_available": order_family_summary_bundle is not None,
            "whole_run_spatial_available": spatial_coherence_bundle is not None,
        },
    )


def run_persist_analysis_summary_stage(
    *,
    db: RunPersistence,
    run_id: str,
    summary: PersistedAnalysis,
) -> PostAnalysisStageResult:
    stage_name = "PersistAnalysisSummaryStage"
    stage_start = time.monotonic()
    try:
        sync_run_persistence_call(db, "astore_analysis", run_id, summary)
    except (aiosqlite.Error, OSError, MemoryError) as exc:
        raise_stage_failure(
            stage_name=stage_name,
            stage_start=stage_start,
            exc=exc,
            diagnostic_context={"run_id": run_id},
        )
    return make_stage_result(
        stage_name=stage_name,
        status="ok",
        stage_start=stage_start,
        diagnostic_context={"run_id": run_id},
    )


def execute_post_analysis(
    *,
    run_id: str,
    db: RunPersistence,
    analysis_runner: PostAnalysisRunner,
    load_run: PostAnalysisLoader = load_post_analysis_run,
    whole_run_artifact_builder: WholeRunArtifactBuilder | None = None,
    whole_run_context_builder: WholeRunContextBuilder | None = None,
    whole_run_order_trace_builder: WholeRunOrderTraceBuilder | None = None,
    whole_run_order_trace_summary_builder: WholeRunOrderTraceSummaryBuilder | None = None,
    whole_run_order_family_summary_builder: WholeRunOrderFamilySummaryBuilder | None = None,
    whole_run_spatial_coherence_builder: WholeRunSpatialCoherenceBuilder | None = None,
    whole_run_diagnosis_summary_builder: WholeRunDiagnosisSummaryBuilder | None = None,
    defer_retryable_error_storage: bool = False,
) -> PostAnalysisAttemptResult:
    analysis_start = time.monotonic()
    resolved_builders = resolve_whole_run_builders(
        whole_run_artifact_builder=whole_run_artifact_builder,
        whole_run_context_builder=whole_run_context_builder,
        whole_run_order_trace_builder=whole_run_order_trace_builder,
        whole_run_order_trace_summary_builder=whole_run_order_trace_summary_builder,
        whole_run_order_family_summary_builder=whole_run_order_family_summary_builder,
        whole_run_spatial_coherence_builder=whole_run_spatial_coherence_builder,
        whole_run_diagnosis_summary_builder=whole_run_diagnosis_summary_builder,
    )
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
        load_stage = run_load_run_stage(
            run_id=run_id,
            db=db,
            load_run=load_run,
            analysis_start=analysis_start,
            defer_retryable_error_storage=defer_retryable_error_storage,
        )
        _log_stage_result(run_id, load_stage.stage_result)
        if load_stage.terminal_result is not None:
            if load_stage.stage_result.diagnostic_context.get("failure_kind") == "missing_metadata":
                span.set_attribute("vibesensor.failure_kind", "missing_metadata")
            if load_stage.stage_result.diagnostic_context.get("failure_kind") == "no_samples":
                span.set_attribute("vibesensor.failure_kind", "no_samples")
            return load_stage.terminal_result

        loaded = load_stage.loaded
        assert loaded is not None
        try:
            input_stage = run_build_post_analysis_input_stage(loaded)
            _log_stage_result(loaded.run_id, input_stage.stage_result)

            whole_run_stage = run_whole_run_pipeline_stages(
                db=db,
                loaded=loaded,
                run_input=input_stage.run_input,
                builders=resolved_builders,
            )
            for stage_result in whole_run_stage.stage_results:
                _log_stage_result(loaded.run_id, stage_result)

            run_input = input_stage.run_input
            span.set_attribute("vibesensor.sample_count", len(run_input.samples))
            summary, report_facts_stage = run_build_report_facts_stage(
                run_input=run_input,
                analysis_runner=analysis_runner,
                whole_run_output=whole_run_stage,
                diagnosis_summary_builder=resolved_builders.diagnosis_summary_builder,
            )
            _log_stage_result(loaded.run_id, report_facts_stage)

            persist_summary_stage = run_persist_analysis_summary_stage(
                db=db,
                run_id=loaded.run_id,
                summary=summary,
            )
            _log_stage_result(loaded.run_id, persist_summary_stage)
        except PostAnalysisStageFailure as stage_failure:
            mark_span_error(span, stage_failure.cause)
            span.set_attribute("vibesensor.failed_stage", stage_failure.stage_result.stage_name)
            _log_stage_result(loaded.run_id, stage_failure.stage_result)
            exc = stage_failure.cause
            if defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
                return _retryable_failure_result(
                    run_id=loaded.run_id,
                    analysis_start=analysis_start,
                    exc=exc,
                    stage_name=stage_failure.stage_result.stage_name,
                )
            return _persistence_failure_result(
                run_id=loaded.run_id,
                analysis_start=analysis_start,
                exc=exc,
                db=db,
                stage_name=stage_failure.stage_result.stage_name,
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
        sync_run_persistence_call(db, "astore_analysis_error", run_id, completed_error)
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
    stage_name: str | None = None,
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
            stage_name=stage_name,
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
    stage_name: str | None = None,
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
            stage_name=stage_name,
        ),
    )
    completed_error = str(exc)
    callback_errors = (callback_error,)

    try:
        sync_run_persistence_call(db, "astore_analysis_error", run_id, completed_error)
    except aiosqlite.Error as store_exc:
        LOGGER.warning(
            "Failed to store analysis error for run %s",
            run_id,
            exc_info=True,
            extra=log_extra(
                event="post_analysis_error_persist_failed",
                run_id=run_id,
                error_message=str(store_exc),
                stage_name=stage_name,
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
