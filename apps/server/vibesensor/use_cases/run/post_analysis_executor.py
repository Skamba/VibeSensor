"""Post-analysis execution as one explicit sequence of stage functions.

``execute_post_analysis`` runs these stages in order. Each stage produces a
``PostAnalysisStageResult`` that is logged when its status is not ``ok``:

1. ``LoadRunStage`` loads metadata and summary rows. Missing metadata or an
   empty run ends the attempt with a stored terminal error.
2. ``BuildPostAnalysisInputStage`` shapes the canonical ``PostAnalysisRunInput``.
3. Whole-run sidecar stages: ``BuildWholeRunSpectraStage``,
   ``BuildWholeRunContextStage``, ``BuildOrderTraceStage``,
   ``BuildOrderTraceSummaryStage``, ``BuildOrderFamilySummaryStage``,
   ``BuildSpatialSummaryStage`` and ``PersistArtifactsStage``. Each is skipped
   when its raw-capture or upstream-bundle prerequisites are missing.
4. ``BuildReportFactsStage`` runs the sample-based analysis and folds the
   whole-run facts into the persisted analysis.
5. ``PersistAnalysisSummaryStage`` stores the persisted analysis.

A storage or memory error (``sqlite3.Error``, ``OSError``, ``MemoryError``)
inside a stage aborts the sequence. The error is either deferred for a retry
or stored as the run's analysis error.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal, NoReturn, Protocol

from opentelemetry.trace import Span, SpanKind

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawCaptureSensorRange
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest
from vibesensor.use_cases.diagnostics._validation import MissingStrengthMetricsError
from vibesensor.use_cases.diagnostics.orders.whole_run_family_summaries import (
    WholeRunOrderFamilySummaryArtifactBundle,
    build_whole_run_order_family_summary_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WholeRunOrderTraceSummaryArtifactBundle,
    build_whole_run_order_trace_summary_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WholeRunOrderTraceArtifactBundle,
    build_whole_run_order_trace_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WholeRunContextArtifactBundle,
    build_whole_run_context_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_coherence import (
    WholeRunSpatialCoherenceArtifactBundle,
    build_whole_run_spatial_coherence_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    RawCaptureRangeReader,
    WholeRunSpectralArtifactBundle,
    WholeRunSpectralBuildResult,
    build_whole_run_spectral_artifact_bundle_from_ranges,
)
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
from vibesensor.use_cases.run.post_analysis_raw_capture_policy import (
    WholeRunRawCapturePolicy,
    assess_whole_run_raw_capture_policy,
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
    build_diagnosis_summary_rows,
    ranked_whole_run_order_summaries,
    ranked_whole_run_spatial_summaries,
    refresh_report_fallback_metadata,
)

LOGGER = logging.getLogger(__name__)

# MissingStrengthMetricsError is a data outcome (recording shorter than one
# analysis window), so it fails the run instead of halting the worker.
_STAGE_ERRORS = (sqlite3.Error, OSError, MemoryError, MissingStrengthMetricsError)

type PostAnalysisStageStatus = Literal["ok", "skipped", "degraded", "failed"]


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
class PostAnalysisExecutionConfig:
    analysis_runner: PostAnalysisRunner
    load_run: PostAnalysisLoader = load_post_analysis_run
    defer_retryable_error_storage: bool = False


@dataclass(frozen=True, slots=True)
class PostAnalysisStageResult:
    """Structured result for one post-analysis stage."""

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


@dataclass(frozen=True, slots=True)
class WholeRunPipelineStageOutput:
    """Artifacts and stage reports from the whole-run sidecar stages."""

    stage_results: tuple[PostAnalysisStageResult, ...]
    stored_artifact_manifest: WholeRunArtifactManifest | None = None
    spectral_result: WholeRunSpectralBuildResult | None = None
    spectral_bundle: WholeRunSpectralArtifactBundle | None = None
    context_bundle: WholeRunContextArtifactBundle | None = None
    order_trace_bundle: WholeRunOrderTraceArtifactBundle | None = None
    order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle | None = None
    order_family_summary_bundle: WholeRunOrderFamilySummaryArtifactBundle | None = None
    spatial_coherence_bundle: WholeRunSpatialCoherenceArtifactBundle | None = None


@dataclass(frozen=True, slots=True)
class StoredWholeRunArtifactBundle:
    """Generic sidecar bundle shape for final manifest persistence."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def execute_post_analysis(
    *,
    run_id: str,
    db: RunPersistence,
    config: PostAnalysisExecutionConfig,
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
            return _run_stages(
                run_id=run_id,
                db=db,
                config=config,
                analysis_start=analysis_start,
                span=span,
            )
        except PostAnalysisStageFailure as stage_failure:
            return _handle_stage_failure(
                span,
                stage_failure,
                run_id=run_id,
                db=db,
                config=config,
                analysis_start=analysis_start,
            )


def _run_stages(
    *,
    run_id: str,
    db: RunPersistence,
    config: PostAnalysisExecutionConfig,
    analysis_start: float,
    span: Span,
) -> PostAnalysisAttemptResult:
    load_stage = run_load_run_stage(
        run_id=run_id,
        db=db,
        load_run=config.load_run,
        analysis_start=analysis_start,
        defer_retryable_error_storage=config.defer_retryable_error_storage,
    )
    _log_stage_result(run_id, load_stage.stage_result)
    if load_stage.terminal_result is not None:
        failure_kind = load_stage.stage_result.diagnostic_context.get("failure_kind")
        if failure_kind in {"missing_metadata", "no_samples"}:
            span.set_attribute("vibesensor.failure_kind", failure_kind)
        return load_stage.terminal_result
    loaded = load_stage.loaded
    assert loaded is not None

    input_stage = run_build_post_analysis_input_stage(loaded)
    _log_stage_result(run_id, input_stage.stage_result)
    run_input = input_stage.run_input

    whole_run_output = run_whole_run_pipeline_stages(db=db, loaded=loaded, run_input=run_input)
    for stage_result in whole_run_output.stage_results:
        _log_stage_result(run_id, stage_result)

    summary, report_facts_stage = run_build_report_facts_stage(
        run_input=run_input,
        analysis_runner=config.analysis_runner,
        whole_run_output=whole_run_output,
    )
    _log_stage_result(run_id, report_facts_stage)

    persist_stage = run_persist_analysis_summary_stage(
        db=db,
        run_id=loaded.run_id,
        summary=summary,
    )
    _log_stage_result(run_id, persist_stage)

    duration_s = time.monotonic() - analysis_start
    span.set_attribute("vibesensor.sample_count", len(run_input.samples))
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


def _handle_stage_failure(
    span: Span,
    stage_failure: PostAnalysisStageFailure,
    *,
    run_id: str,
    db: RunPersistence,
    config: PostAnalysisExecutionConfig,
    analysis_start: float,
) -> PostAnalysisAttemptResult:
    mark_span_error(span, stage_failure.cause)
    span.set_attribute("vibesensor.failed_stage", stage_failure.stage_result.stage_name)
    _log_stage_result(run_id, stage_failure.stage_result)
    exc = stage_failure.cause
    if config.defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
        return _retryable_failure_result(
            run_id=run_id,
            analysis_start=analysis_start,
            exc=exc,
            stage_name=stage_failure.stage_result.stage_name,
        )
    return _persistence_failure_result(
        run_id=run_id,
        analysis_start=analysis_start,
        exc=exc,
        db=db,
        stage_name=stage_failure.stage_result.stage_name,
    )


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


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


def _skipped_stage_result(
    stage_name: str,
    stage_start: float,
    reason: str,
) -> PostAnalysisStageResult:
    return make_stage_result(
        stage_name=stage_name,
        status="skipped",
        stage_start=stage_start,
        diagnostic_context={"reason": reason},
    )


def _built_stage_result(
    stage_name: str,
    stage_start: float,
    result: object | None,
    *,
    manifest: WholeRunArtifactManifest | None = None,
    status: PostAnalysisStageStatus = "ok",
    warnings: tuple[str, ...] = (),
    diagnostic_context: JsonObject | None = None,
    none_diagnostic_context: JsonObject | None = None,
) -> PostAnalysisStageResult:
    """Report a stage whose builder ran; a ``None`` result reports as skipped."""
    if result is None:
        return make_stage_result(
            stage_name=stage_name,
            status="skipped",
            stage_start=stage_start,
            warnings=warnings,
            diagnostic_context={
                **(none_diagnostic_context or {}),
                "reason": "builder_returned_none",
            },
        )
    return make_stage_result(
        stage_name=stage_name,
        status=status,
        stage_start=stage_start,
        artifacts_created=(
            () if manifest is None else tuple(item.artifact_key for item in manifest.artifacts)
        ),
        warnings=warnings,
        diagnostic_context=diagnostic_context,
    )


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


@contextmanager
def _stage_failures(stage_name: str, stage_start: float, run_id: str) -> Iterator[None]:
    """Convert storage/memory errors raised inside a stage into a stage failure."""
    try:
        yield
    except _STAGE_ERRORS as exc:
        raise_stage_failure(
            stage_name=stage_name,
            stage_start=stage_start,
            exc=exc,
            diagnostic_context={"run_id": run_id},
        )


def warning_codes(warnings: tuple[object, ...]) -> tuple[str, ...]:
    codes: list[str] = []
    for warning in warnings:
        code = getattr(warning, "code", None)
        if isinstance(code, str) and code:
            codes.append(code)
    return tuple(codes)


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


# ---------------------------------------------------------------------------
# Load and input stages
# ---------------------------------------------------------------------------


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
    except _STAGE_ERRORS as exc:
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
    with _stage_failures(stage_name, stage_start, loaded.run_id):
        run_input = build_post_analysis_input(loaded)
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


# ---------------------------------------------------------------------------
# Whole-run sidecar stages
# ---------------------------------------------------------------------------


def run_whole_run_pipeline_stages(
    *,
    db: RunPersistence,
    loaded: LoadedPostAnalysisRun,
    run_input: PostAnalysisRunInput,
) -> WholeRunPipelineStageOutput:
    """Build, then persist, the dense whole-run sidecar artifacts for one run."""
    run_id = loaded.run_id
    policy = assess_whole_run_raw_capture_policy(loaded)
    stage_results: list[PostAnalysisStageResult] = []

    spectral_result = _whole_run_spectra_stage(stage_results, db=db, loaded=loaded, policy=policy)
    spectral_bundle = spectral_result.bundle if spectral_result is not None else None
    context_bundle = _whole_run_context_stage(
        stage_results,
        run_id=run_id,
        run_input=run_input,
        policy=policy,
        spectral_result=spectral_result,
    )
    order_trace_bundle = _order_trace_stage(
        stage_results,
        run_id=run_id,
        run_input=run_input,
        spectral_bundle=spectral_bundle,
        context_bundle=context_bundle,
    )
    order_trace_summary_bundle = _order_trace_summary_stage(
        stage_results,
        run_id=run_id,
        order_trace_bundle=order_trace_bundle,
        context_bundle=context_bundle,
    )
    order_family_summary_bundle = _order_family_summary_stage(
        stage_results,
        run_id=run_id,
        order_trace_bundle=order_trace_bundle,
        order_trace_summary_bundle=order_trace_summary_bundle,
        context_bundle=context_bundle,
    )
    spatial_coherence_bundle = _spatial_summary_stage(
        stage_results,
        run_id=run_id,
        run_input=run_input,
        spectral_bundle=spectral_bundle,
        context_bundle=context_bundle,
        order_trace_bundle=order_trace_bundle,
    )
    stored_artifact_manifest = _persist_artifacts_stage(
        stage_results,
        db=db,
        run_id=run_id,
        merged_bundle=merge_whole_run_artifact_bundles(
            spectral_bundle,
            context_bundle,
            order_trace_bundle,
            order_trace_summary_bundle,
            order_family_summary_bundle,
            spatial_coherence_bundle,
        ),
    )
    return WholeRunPipelineStageOutput(
        stage_results=tuple(stage_results),
        stored_artifact_manifest=stored_artifact_manifest,
        spectral_result=spectral_result,
        spectral_bundle=spectral_bundle,
        context_bundle=context_bundle,
        order_trace_bundle=order_trace_bundle,
        order_trace_summary_bundle=order_trace_summary_bundle,
        order_family_summary_bundle=order_family_summary_bundle,
        spatial_coherence_bundle=spatial_coherence_bundle,
    )


def _whole_run_spectra_stage(
    stage_results: list[PostAnalysisStageResult],
    *,
    db: RunPersistence,
    loaded: LoadedPostAnalysisRun,
    policy: WholeRunRawCapturePolicy,
) -> WholeRunSpectralBuildResult | None:
    stage_name = "BuildWholeRunSpectraStage"
    stage_start = time.monotonic()
    if not policy.raw_capture_prerequisites_met():
        stage_results.append(
            _skipped_stage_result(stage_name, stage_start, policy.raw_capture_skip_reason())
        )
        return None
    raw_capture_manifest = policy.manifest
    assert raw_capture_manifest is not None
    with _stage_failures(stage_name, stage_start, loaded.run_id):
        result = build_whole_run_spectral_artifact_bundle_from_ranges(
            run_id=loaded.run_id,
            metadata=loaded.metadata,
            raw_capture_manifest=raw_capture_manifest,
            raw_range_reader=_raw_range_reader(db, loaded),
        )
    stage_results.append(
        _built_stage_result(
            stage_name,
            stage_start,
            result,
            manifest=result.bundle.manifest if result.bundle is not None else None,
            warnings=warning_codes(tuple(result.coverage_summary.warnings)),
            diagnostic_context={
                "bundle_available": result.bundle is not None,
                "coverage_confidence": result.coverage_summary.coverage_confidence,
            },
        )
    )
    return result


def _raw_range_reader(db: RunPersistence, loaded: LoadedPostAnalysisRun) -> RawCaptureRangeReader:
    """Read raw waveform ranges for *loaded* through the persistence port."""

    def read_range(
        client_id: str,
        *,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None:
        return db.load_raw_capture_sensor_range(
            loaded.run_id,
            client_id,
            sample_start=sample_start,
            sample_count=sample_count,
        )

    return read_range


def _whole_run_context_stage(
    stage_results: list[PostAnalysisStageResult],
    *,
    run_id: str,
    run_input: PostAnalysisRunInput,
    policy: WholeRunRawCapturePolicy,
    spectral_result: WholeRunSpectralBuildResult | None,
) -> WholeRunContextArtifactBundle | None:
    stage_name = "BuildWholeRunContextStage"
    stage_start = time.monotonic()
    if not policy.raw_capture_prerequisites_met():
        stage_results.append(
            _skipped_stage_result(stage_name, stage_start, policy.raw_capture_skip_reason())
        )
        return None
    raw_capture_manifest = policy.manifest
    assert raw_capture_manifest is not None
    # Prefer the spectral window plan so context labels align with the spectra;
    # otherwise plan windows from the raw sample count (reported as degraded).
    window_plan = spectral_result.window_plan if spectral_result is not None else None
    total_sample_count: int | None = None
    build_mode = "window_plan"
    status: PostAnalysisStageStatus = "ok"
    with _stage_failures(stage_name, stage_start, run_id):
        if window_plan is None:
            build_mode = "total_sample_count_fallback"
            status = "degraded"
            total_sample_count = whole_run_total_sample_count(raw_capture_manifest)
            if total_sample_count < 0:
                raise ValueError("whole-run context builder requires total_sample_count >= 0")
        bundle = build_whole_run_context_artifact_bundle(
            run_id=run_input.run_id,
            metadata=run_input.context,
            samples=run_input.context_samples,
            total_sample_count=total_sample_count,
            window_plan=window_plan,
        )
    stage_results.append(
        _built_stage_result(
            stage_name,
            stage_start,
            bundle,
            manifest=bundle.manifest if bundle is not None else None,
            status=status,
            diagnostic_context={"build_mode": build_mode},
            none_diagnostic_context={"build_mode": build_mode},
        )
    )
    return bundle


def _order_trace_stage(
    stage_results: list[PostAnalysisStageResult],
    *,
    run_id: str,
    run_input: PostAnalysisRunInput,
    spectral_bundle: WholeRunSpectralArtifactBundle | None,
    context_bundle: WholeRunContextArtifactBundle | None,
) -> WholeRunOrderTraceArtifactBundle | None:
    stage_name = "BuildOrderTraceStage"
    stage_start = time.monotonic()
    if spectral_bundle is None or context_bundle is None:
        stage_results.append(
            _skipped_stage_result(stage_name, stage_start, "missing_prerequisites")
        )
        return None
    with _stage_failures(stage_name, stage_start, run_id):
        bundle = build_whole_run_order_trace_artifact_bundle(
            run_id=run_input.run_id,
            metadata=run_input.context,
            spectral_manifest=spectral_bundle.manifest,
            spectral_artifact_contents=spectral_bundle.artifact_contents,
            context_labels=context_bundle.labels,
            samples=run_input.context_samples,
            lang=run_input.language,
        )
    stage_results.append(
        _built_stage_result(
            stage_name,
            stage_start,
            bundle,
            manifest=bundle.manifest if bundle is not None else None,
        )
    )
    return bundle


def _order_trace_summary_stage(
    stage_results: list[PostAnalysisStageResult],
    *,
    run_id: str,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle | None,
    context_bundle: WholeRunContextArtifactBundle | None,
) -> WholeRunOrderTraceSummaryArtifactBundle | None:
    stage_name = "BuildOrderTraceSummaryStage"
    stage_start = time.monotonic()
    if order_trace_bundle is None or context_bundle is None:
        stage_results.append(
            _skipped_stage_result(stage_name, stage_start, "missing_prerequisites")
        )
        return None
    with _stage_failures(stage_name, stage_start, run_id):
        bundle = build_whole_run_order_trace_summary_artifact_bundle(
            order_trace_bundle=order_trace_bundle,
            context_labels=context_bundle.labels,
        )
    stage_results.append(
        _built_stage_result(
            stage_name,
            stage_start,
            bundle,
            manifest=bundle.manifest if bundle is not None else None,
        )
    )
    return bundle


def _order_family_summary_stage(
    stage_results: list[PostAnalysisStageResult],
    *,
    run_id: str,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle | None,
    order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle | None,
    context_bundle: WholeRunContextArtifactBundle | None,
) -> WholeRunOrderFamilySummaryArtifactBundle | None:
    stage_name = "BuildOrderFamilySummaryStage"
    stage_start = time.monotonic()
    if order_trace_bundle is None or order_trace_summary_bundle is None or context_bundle is None:
        stage_results.append(
            _skipped_stage_result(stage_name, stage_start, "missing_prerequisites")
        )
        return None
    with _stage_failures(stage_name, stage_start, run_id):
        bundle = build_whole_run_order_family_summary_artifact_bundle(
            order_trace_bundle=order_trace_bundle,
            order_trace_summary_bundle=order_trace_summary_bundle,
            context_labels=context_bundle.labels,
        )
    stage_results.append(
        _built_stage_result(
            stage_name,
            stage_start,
            bundle,
            manifest=bundle.manifest if bundle is not None else None,
        )
    )
    return bundle


def _spatial_summary_stage(
    stage_results: list[PostAnalysisStageResult],
    *,
    run_id: str,
    run_input: PostAnalysisRunInput,
    spectral_bundle: WholeRunSpectralArtifactBundle | None,
    context_bundle: WholeRunContextArtifactBundle | None,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle | None,
) -> WholeRunSpatialCoherenceArtifactBundle | None:
    stage_name = "BuildSpatialSummaryStage"
    stage_start = time.monotonic()
    if spectral_bundle is None or context_bundle is None or order_trace_bundle is None:
        stage_results.append(
            _skipped_stage_result(stage_name, stage_start, "missing_prerequisites")
        )
        return None
    bundle: WholeRunSpatialCoherenceArtifactBundle | None = None
    with _stage_failures(stage_name, stage_start, run_id):
        # Spatial coherence is only defined over order-trace points.
        if order_trace_bundle.points:
            bundle = build_whole_run_spatial_coherence_artifact_bundle(
                order_trace_bundle=order_trace_bundle,
                spectral_manifest=spectral_bundle.manifest,
                spectral_artifact_contents=spectral_bundle.artifact_contents,
                context_labels=context_bundle.labels,
                samples=run_input.samples,
                lang=run_input.language,
            )
    stage_results.append(
        _built_stage_result(
            stage_name,
            stage_start,
            bundle,
            manifest=bundle.manifest if bundle is not None else None,
        )
    )
    return bundle


def _persist_artifacts_stage(
    stage_results: list[PostAnalysisStageResult],
    *,
    db: RunPersistence,
    run_id: str,
    merged_bundle: StoredWholeRunArtifactBundle | None,
) -> WholeRunArtifactManifest | None:
    stage_name = "PersistArtifactsStage"
    stage_start = time.monotonic()
    if merged_bundle is None:
        stage_results.append(
            _skipped_stage_result(stage_name, stage_start, "no_artifacts_to_persist")
        )
        return None
    with _stage_failures(stage_name, stage_start, run_id):
        stored_manifest = db.store_whole_run_artifacts(
            run_id,
            merged_bundle.manifest,
            artifact_contents=merged_bundle.artifact_contents,
        )
        if stored_manifest is None:
            raise OSError(f"Failed to persist whole-run artifacts for run {run_id}")
    stage_results.append(
        _built_stage_result(
            stage_name,
            stage_start,
            stored_manifest,
            manifest=stored_manifest,
            diagnostic_context={"artifact_count": len(stored_manifest.artifacts)},
        )
    )
    return stored_manifest


def whole_run_total_sample_count(manifest: RawCaptureManifest) -> int:
    if manifest.sensors:
        return max(int(sensor.sample_count) for sensor in manifest.sensors)
    return max(0, int(manifest.total_samples))


def merge_whole_run_artifact_bundles(
    *bundles: (
        WholeRunSpectralArtifactBundle
        | WholeRunContextArtifactBundle
        | WholeRunOrderTraceArtifactBundle
        | WholeRunOrderTraceSummaryArtifactBundle
        | WholeRunOrderFamilySummaryArtifactBundle
        | WholeRunSpatialCoherenceArtifactBundle
        | StoredWholeRunArtifactBundle
        | None
    ),
) -> StoredWholeRunArtifactBundle | None:
    active_bundles = [bundle for bundle in bundles if bundle is not None]
    if not active_bundles:
        return None
    base_manifest = active_bundles[0].manifest
    merged_artifacts = list(base_manifest.artifacts)
    merged_contents = dict(active_bundles[0].artifact_contents)
    for bundle in active_bundles[1:]:
        manifest = bundle.manifest
        if (
            manifest.run_id != base_manifest.run_id
            or manifest.relative_dir != base_manifest.relative_dir
            or manifest.window_policy != base_manifest.window_policy
            or manifest.total_window_count != base_manifest.total_window_count
        ):
            raise ValueError("whole-run artifact bundles must share the same run/window plan")
        for artifact in manifest.artifacts:
            if artifact.artifact_key in merged_contents:
                raise ValueError(
                    "whole-run artifact bundles must not reuse artifact keys: "
                    f"{artifact.artifact_key}"
                )
            if artifact.artifact_key not in bundle.artifact_contents:
                raise ValueError(
                    f"whole-run artifact bundle missing bytes for {artifact.artifact_key}"
                )
            merged_artifacts.append(artifact)
        merged_contents.update(bundle.artifact_contents)
    return StoredWholeRunArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id=base_manifest.run_id,
            relative_dir=base_manifest.relative_dir,
            window_policy=base_manifest.window_policy,
            total_window_count=base_manifest.total_window_count,
            artifacts=tuple(merged_artifacts),
            created_at=base_manifest.created_at,
            schema_version=base_manifest.schema_version,
            storage_type=base_manifest.storage_type,
            algorithm_versions=dict(base_manifest.algorithm_versions),
            configuration=dict(base_manifest.configuration),
            source_raw_manifests=base_manifest.source_raw_manifests,
        ),
        artifact_contents=merged_contents,
    )


# ---------------------------------------------------------------------------
# Report-facts and persist stages
# ---------------------------------------------------------------------------


def run_build_report_facts_stage(
    *,
    run_input: PostAnalysisRunInput,
    analysis_runner: PostAnalysisRunner,
    whole_run_output: WholeRunPipelineStageOutput,
) -> tuple[PersistedAnalysis, PostAnalysisStageResult]:
    stage_name = "BuildReportFactsStage"
    stage_start = time.monotonic()
    with _stage_failures(stage_name, stage_start, run_input.run_id):
        raw_summary = analysis_runner(run_input)
        summary = (
            raw_summary
            if isinstance(raw_summary, PersistedAnalysis)
            else PersistedAnalysis.from_json_object(raw_summary)
        )

    spectral_result = whole_run_output.spectral_result
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
            spectral_bundle=whole_run_output.spectral_bundle,
        )
        summary = append_run_context_warnings(summary, spectral_result.coverage_summary.warnings)
    if context_bundle is not None:
        summary = append_whole_run_context(summary, context_bundle)

    # Diagnosis fusion sees the analysis metadata as it stood before the
    # order/spatial summaries below were folded in.
    analysis_metadata_payload = summary.to_json_object().get("analysis_metadata")
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
        diagnosis_summaries = build_diagnosis_summary_rows(
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
    with _stage_failures(stage_name, stage_start, run_id):
        db.store_analysis(run_id, summary)
    return make_stage_result(
        stage_name=stage_name,
        status="ok",
        stage_start=stage_start,
        diagnostic_context={"run_id": run_id},
    )


# ---------------------------------------------------------------------------
# Failure outcomes
# ---------------------------------------------------------------------------


def _store_load_error(
    *,
    db: RunPersistence,
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
