"""Execution and persistence coordination for background post-analysis."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn, Protocol

import aiosqlite
from opentelemetry.trace import SpanKind

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.run_context_warning import (
    RunContextWarningsInput,
    normalize_run_context_warnings,
)
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTraceSummary
from vibesensor.use_cases.diagnostics.orders.whole_run_family_summaries import (
    WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
    WholeRunOrderFamilySummaryArtifactBundle,
    build_whole_run_order_family_summary_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
    WholeRunOrderTraceSummaryArtifactBundle,
    build_whole_run_order_trace_summary_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    WholeRunOrderTraceArtifactBundle,
    build_whole_run_order_trace_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
    WholeRunContextArtifactBundle,
    build_whole_run_context_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_contracts import (
    WholeRunDiagnosisSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_ranking import (
    build_whole_run_diagnosis_summaries,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_coherence import (
    WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
    WholeRunSpatialCoherenceArtifactBundle,
    build_whole_run_spatial_coherence_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunSpectralArtifactBundle,
    WholeRunSpectralBuildResult,
    WholeRunSpectralCoverageSummary,
    build_whole_run_spectral_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import WholeRunWindowPlan
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

LOGGER = logging.getLogger(__name__)


def _sync_call(db: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Invoke ``db.<method_name>`` synchronously from a worker thread.

    If the db exposes a real async method and an engine loop runner, go
    through that loop so aiosqlite futures resolve on the connection's
    owning loop. Otherwise (test fakes, sync stubs) fall back to
    ``asyncio.run`` or direct sync call.
    """
    method = getattr(db, method_name)
    result = method(*args, **kwargs)
    if asyncio.iscoroutine(result):
        runner = getattr(db, "_run_on_engine_loop", None)
        if callable(runner):
            return runner(result)
        return asyncio.run(result)
    return result


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


class WholeRunArtifactBuilder(Protocol):
    """Injected boundary for building dense whole-run sidecar artifacts."""

    def __call__(
        self,
        *,
        run_id: str,
        metadata: RunMetadata,
        raw_capture: RawRunCapture,
    ) -> WholeRunSpectralBuildResult: ...


class WholeRunContextBuilder(Protocol):
    """Injected boundary for building dense whole-run context sidecars."""

    def __call__(
        self,
        *,
        run: PostAnalysisRunInput,
        total_sample_count: int | None = None,
        window_plan: WholeRunWindowPlan | None = None,
    ) -> WholeRunContextArtifactBundle | None: ...


class WholeRunOrderTraceBuilder(Protocol):
    """Injected boundary for building dense whole-run order-trace sidecars."""

    def __call__(
        self,
        *,
        run: PostAnalysisRunInput,
        spectral_bundle: WholeRunSpectralArtifactBundle,
        context_bundle: WholeRunContextArtifactBundle,
    ) -> WholeRunOrderTraceArtifactBundle | None: ...


class WholeRunOrderTraceSummaryBuilder(Protocol):
    """Injected boundary for building compact whole-run order-trace summaries."""

    def __call__(
        self,
        *,
        order_trace_bundle: WholeRunOrderTraceArtifactBundle,
        context_bundle: WholeRunContextArtifactBundle,
    ) -> WholeRunOrderTraceSummaryArtifactBundle | None: ...


class WholeRunOrderFamilySummaryBuilder(Protocol):
    """Injected boundary for building family-level whole-run order summaries."""

    def __call__(
        self,
        *,
        order_trace_bundle: WholeRunOrderTraceArtifactBundle,
        order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle,
        context_bundle: WholeRunContextArtifactBundle,
    ) -> WholeRunOrderFamilySummaryArtifactBundle | None: ...


class WholeRunSpatialCoherenceBuilder(Protocol):
    """Injected boundary for building candidate-level whole-run spatial coherence."""

    def __call__(
        self,
        *,
        run: PostAnalysisRunInput,
        spectral_bundle: WholeRunSpectralArtifactBundle,
        context_bundle: WholeRunContextArtifactBundle,
        order_trace_bundle: WholeRunOrderTraceArtifactBundle,
    ) -> WholeRunSpatialCoherenceArtifactBundle | None: ...


class WholeRunDiagnosisSummaryBuilder(Protocol):
    """Injected boundary for building compact fused whole-run diagnosis summaries."""

    def __call__(
        self,
        *,
        analysis_metadata: Mapping[str, object],
        context_bundle: WholeRunContextArtifactBundle,
        order_summaries: tuple[OrderTraceSummary, ...],
        spatial_summaries: tuple[SpatialEvidenceSummary, ...],
    ) -> tuple[WholeRunDiagnosisSummary, ...]: ...


@dataclass(frozen=True, slots=True)
class _StoredWholeRunArtifactBundle:
    """Generic sidecar bundle shape for final manifest persistence."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]


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
    """Artifacts and stage reports from the whole-run sidecar pipeline."""

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
class ResolvedWholeRunBuilders:
    """Resolved builder callables used by the explicit whole-run pipeline stages."""

    artifact_builder: WholeRunArtifactBuilder
    context_builder: WholeRunContextBuilder
    order_trace_builder: WholeRunOrderTraceBuilder
    order_trace_summary_builder: WholeRunOrderTraceSummaryBuilder
    order_family_summary_builder: WholeRunOrderFamilySummaryBuilder
    spatial_coherence_builder: WholeRunSpatialCoherenceBuilder
    diagnosis_summary_builder: WholeRunDiagnosisSummaryBuilder


class PostAnalysisStageFailure(Exception):
    """Retryable or persistence-bound stage failure with explicit stage metadata."""

    def __init__(self, stage_result: PostAnalysisStageResult, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.stage_result = stage_result
        self.cause = cause


def _duration_ms(stage_start: float) -> int:
    return max(0, int(round((time.monotonic() - stage_start) * 1000)))


def _make_stage_result(
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
        duration_ms=_duration_ms(stage_start),
        artifacts_created=artifacts_created,
        warnings=warnings,
        diagnostic_context={} if diagnostic_context is None else diagnostic_context,
    )


def _artifact_keys(manifest: WholeRunArtifactManifest | None) -> tuple[str, ...]:
    if manifest is None:
        return ()
    return tuple(artifact.artifact_key for artifact in manifest.artifacts)


def _warning_codes(warnings: tuple[object, ...]) -> tuple[str, ...]:
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


def _raise_stage_failure(
    *,
    stage_name: str,
    stage_start: float,
    exc: BaseException,
    diagnostic_context: JsonObject | None = None,
) -> NoReturn:
    raise PostAnalysisStageFailure(
        _make_stage_result(
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


def resolve_whole_run_builders(
    *,
    whole_run_artifact_builder: WholeRunArtifactBuilder | None,
    whole_run_context_builder: WholeRunContextBuilder | None,
    whole_run_order_trace_builder: WholeRunOrderTraceBuilder | None,
    whole_run_order_trace_summary_builder: WholeRunOrderTraceSummaryBuilder | None,
    whole_run_order_family_summary_builder: WholeRunOrderFamilySummaryBuilder | None,
    whole_run_spatial_coherence_builder: WholeRunSpatialCoherenceBuilder | None,
    whole_run_diagnosis_summary_builder: WholeRunDiagnosisSummaryBuilder | None,
) -> ResolvedWholeRunBuilders:
    return ResolvedWholeRunBuilders(
        artifact_builder=(
            _build_whole_run_artifacts
            if whole_run_artifact_builder is None
            else whole_run_artifact_builder
        ),
        context_builder=(
            _build_whole_run_context_artifacts
            if whole_run_context_builder is None
            else whole_run_context_builder
        ),
        order_trace_builder=(
            _build_whole_run_order_trace_artifacts
            if whole_run_order_trace_builder is None
            else whole_run_order_trace_builder
        ),
        order_trace_summary_builder=(
            _build_whole_run_order_trace_summary_artifacts
            if whole_run_order_trace_summary_builder is None
            else whole_run_order_trace_summary_builder
        ),
        order_family_summary_builder=(
            _build_whole_run_order_family_summary_artifacts
            if whole_run_order_family_summary_builder is None
            else whole_run_order_family_summary_builder
        ),
        spatial_coherence_builder=(
            _build_whole_run_spatial_coherence_artifacts
            if whole_run_spatial_coherence_builder is None
            else whole_run_spatial_coherence_builder
        ),
        diagnosis_summary_builder=(
            _build_whole_run_diagnosis_summaries
            if whole_run_diagnosis_summary_builder is None
            else whole_run_diagnosis_summary_builder
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
            stage_result=_make_stage_result(
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
            stage_result=_make_stage_result(
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
            stage_result=_make_stage_result(
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
        stage_result=_make_stage_result(
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
        _raise_stage_failure(
            stage_name=stage_name,
            stage_start=stage_start,
            exc=exc,
            diagnostic_context={"run_id": loaded.run_id},
        )
    return PostAnalysisInputStageOutput(
        run_input=run_input,
        stage_result=_make_stage_result(
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


def run_whole_run_pipeline_stages(
    *,
    db: RunPersistence,
    loaded: LoadedPostAnalysisRun,
    run_input: PostAnalysisRunInput,
    builders: ResolvedWholeRunBuilders,
) -> WholeRunPipelineStageOutput:
    stage_results: list[PostAnalysisStageResult] = []
    spectral_result: WholeRunSpectralBuildResult | None = None
    spectral_bundle: WholeRunSpectralArtifactBundle | None = None
    context_bundle: WholeRunContextArtifactBundle | None = None
    order_trace_bundle: WholeRunOrderTraceArtifactBundle | None = None
    order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle | None = None
    order_family_summary_bundle: WholeRunOrderFamilySummaryArtifactBundle | None = None
    spatial_coherence_bundle: WholeRunSpatialCoherenceArtifactBundle | None = None
    stored_artifact_manifest: WholeRunArtifactManifest | None = None

    spectral_stage_start = time.monotonic()
    if loaded.raw_capture is None:
        stage_results.append(
            _make_stage_result(
                stage_name="BuildWholeRunSpectraStage",
                status="skipped",
                stage_start=spectral_stage_start,
                diagnostic_context={"reason": "raw_capture_missing"},
            )
        )
    else:
        try:
            spectral_result = builders.artifact_builder(
                run_id=loaded.run_id,
                metadata=loaded.metadata,
                raw_capture=loaded.raw_capture,
            )
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            _raise_stage_failure(
                stage_name="BuildWholeRunSpectraStage",
                stage_start=spectral_stage_start,
                exc=exc,
                diagnostic_context={"run_id": loaded.run_id},
            )
        spectral_bundle = spectral_result.bundle
        stage_results.append(
            _make_stage_result(
                stage_name="BuildWholeRunSpectraStage",
                status="ok",
                stage_start=spectral_stage_start,
                artifacts_created=_artifact_keys(
                    spectral_bundle.manifest if spectral_bundle is not None else None
                ),
                warnings=_warning_codes(tuple(spectral_result.coverage_summary.warnings)),
                diagnostic_context={
                    "bundle_available": spectral_bundle is not None,
                    "coverage_confidence": spectral_result.coverage_summary.coverage_confidence,
                },
            )
        )

    context_stage_start = time.monotonic()
    context_status: PostAnalysisStageStatus = "skipped"
    context_diagnostic: JsonObject = {"reason": "raw_capture_manifest_missing"}
    if loaded.raw_capture_manifest is not None:
        try:
            if spectral_result is not None and spectral_result.window_plan is not None:
                context_bundle = builders.context_builder(
                    run=run_input,
                    window_plan=spectral_result.window_plan,
                )
                context_status = "ok"
                context_diagnostic = {"build_mode": "window_plan"}
            else:
                context_bundle = builders.context_builder(
                    run=run_input,
                    total_sample_count=_whole_run_total_sample_count(loaded.raw_capture_manifest),
                )
                context_status = "degraded"
                context_diagnostic = {"build_mode": "total_sample_count_fallback"}
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            _raise_stage_failure(
                stage_name="BuildWholeRunContextStage",
                stage_start=context_stage_start,
                exc=exc,
                diagnostic_context={"run_id": loaded.run_id},
            )
        if context_bundle is None:
            context_status = "skipped"
            context_diagnostic = {**context_diagnostic, "reason": "builder_returned_none"}
    stage_results.append(
        _make_stage_result(
            stage_name="BuildWholeRunContextStage",
            status=context_status,
            stage_start=context_stage_start,
            artifacts_created=_artifact_keys(
                context_bundle.manifest if context_bundle is not None else None
            ),
            diagnostic_context=context_diagnostic,
        )
    )

    order_trace_stage_start = time.monotonic()
    if spectral_bundle is None or context_bundle is None:
        stage_results.append(
            _make_stage_result(
                stage_name="BuildOrderTraceStage",
                status="skipped",
                stage_start=order_trace_stage_start,
                diagnostic_context={"reason": "missing_prerequisites"},
            )
        )
    else:
        try:
            order_trace_bundle = builders.order_trace_builder(
                run=run_input,
                spectral_bundle=spectral_bundle,
                context_bundle=context_bundle,
            )
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            _raise_stage_failure(
                stage_name="BuildOrderTraceStage",
                stage_start=order_trace_stage_start,
                exc=exc,
                diagnostic_context={"run_id": loaded.run_id},
            )
        stage_results.append(
            _make_stage_result(
                stage_name="BuildOrderTraceStage",
                status="ok" if order_trace_bundle is not None else "skipped",
                stage_start=order_trace_stage_start,
                artifacts_created=_artifact_keys(
                    order_trace_bundle.manifest if order_trace_bundle is not None else None
                ),
                diagnostic_context=(
                    {"reason": "builder_returned_none"} if order_trace_bundle is None else {}
                ),
            )
        )

    order_trace_summary_stage_start = time.monotonic()
    if order_trace_bundle is None or context_bundle is None:
        stage_results.append(
            _make_stage_result(
                stage_name="BuildOrderTraceSummaryStage",
                status="skipped",
                stage_start=order_trace_summary_stage_start,
                diagnostic_context={"reason": "missing_prerequisites"},
            )
        )
    else:
        try:
            order_trace_summary_bundle = builders.order_trace_summary_builder(
                order_trace_bundle=order_trace_bundle,
                context_bundle=context_bundle,
            )
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            _raise_stage_failure(
                stage_name="BuildOrderTraceSummaryStage",
                stage_start=order_trace_summary_stage_start,
                exc=exc,
                diagnostic_context={"run_id": loaded.run_id},
            )
        stage_results.append(
            _make_stage_result(
                stage_name="BuildOrderTraceSummaryStage",
                status="ok" if order_trace_summary_bundle is not None else "skipped",
                stage_start=order_trace_summary_stage_start,
                artifacts_created=_artifact_keys(
                    order_trace_summary_bundle.manifest
                    if order_trace_summary_bundle is not None
                    else None
                ),
                diagnostic_context=(
                    {"reason": "builder_returned_none"}
                    if order_trace_summary_bundle is None
                    else {}
                ),
            )
        )

    order_family_stage_start = time.monotonic()
    if order_trace_bundle is None or order_trace_summary_bundle is None or context_bundle is None:
        stage_results.append(
            _make_stage_result(
                stage_name="BuildOrderFamilySummaryStage",
                status="skipped",
                stage_start=order_family_stage_start,
                diagnostic_context={"reason": "missing_prerequisites"},
            )
        )
    else:
        try:
            order_family_summary_bundle = builders.order_family_summary_builder(
                order_trace_bundle=order_trace_bundle,
                order_trace_summary_bundle=order_trace_summary_bundle,
                context_bundle=context_bundle,
            )
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            _raise_stage_failure(
                stage_name="BuildOrderFamilySummaryStage",
                stage_start=order_family_stage_start,
                exc=exc,
                diagnostic_context={"run_id": loaded.run_id},
            )
        stage_results.append(
            _make_stage_result(
                stage_name="BuildOrderFamilySummaryStage",
                status="ok" if order_family_summary_bundle is not None else "skipped",
                stage_start=order_family_stage_start,
                artifacts_created=_artifact_keys(
                    order_family_summary_bundle.manifest
                    if order_family_summary_bundle is not None
                    else None
                ),
                diagnostic_context=(
                    {"reason": "builder_returned_none"}
                    if order_family_summary_bundle is None
                    else {}
                ),
            )
        )

    spatial_stage_start = time.monotonic()
    if spectral_bundle is None or context_bundle is None or order_trace_bundle is None:
        stage_results.append(
            _make_stage_result(
                stage_name="BuildSpatialSummaryStage",
                status="skipped",
                stage_start=spatial_stage_start,
                diagnostic_context={"reason": "missing_prerequisites"},
            )
        )
    else:
        try:
            spatial_coherence_bundle = builders.spatial_coherence_builder(
                run=run_input,
                spectral_bundle=spectral_bundle,
                context_bundle=context_bundle,
                order_trace_bundle=order_trace_bundle,
            )
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            _raise_stage_failure(
                stage_name="BuildSpatialSummaryStage",
                stage_start=spatial_stage_start,
                exc=exc,
                diagnostic_context={"run_id": loaded.run_id},
            )
        stage_results.append(
            _make_stage_result(
                stage_name="BuildSpatialSummaryStage",
                status="ok" if spatial_coherence_bundle is not None else "skipped",
                stage_start=spatial_stage_start,
                artifacts_created=_artifact_keys(
                    spatial_coherence_bundle.manifest
                    if spatial_coherence_bundle is not None
                    else None
                ),
                diagnostic_context=(
                    {"reason": "builder_returned_none"} if spatial_coherence_bundle is None else {}
                ),
            )
        )

    persist_artifacts_stage_start = time.monotonic()
    merged_bundle = _merge_whole_run_artifact_bundles(
        spectral_bundle,
        context_bundle,
        order_trace_bundle,
        order_trace_summary_bundle,
        order_family_summary_bundle,
        spatial_coherence_bundle,
    )
    if merged_bundle is None:
        stage_results.append(
            _make_stage_result(
                stage_name="PersistArtifactsStage",
                status="skipped",
                stage_start=persist_artifacts_stage_start,
                diagnostic_context={"reason": "no_artifacts_to_persist"},
            )
        )
    else:
        try:
            stored_artifact_manifest = _sync_call(
                db,
                "astore_whole_run_artifacts",
                loaded.run_id,
                merged_bundle.manifest,
                artifact_contents=merged_bundle.artifact_contents,
            )
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            _raise_stage_failure(
                stage_name="PersistArtifactsStage",
                stage_start=persist_artifacts_stage_start,
                exc=exc,
                diagnostic_context={"run_id": loaded.run_id},
            )
        if stored_artifact_manifest is None:
            _raise_stage_failure(
                stage_name="PersistArtifactsStage",
                stage_start=persist_artifacts_stage_start,
                exc=OSError(f"Failed to persist whole-run artifacts for run {loaded.run_id}"),
                diagnostic_context={"run_id": loaded.run_id},
            )
        stage_results.append(
            _make_stage_result(
                stage_name="PersistArtifactsStage",
                status="ok",
                stage_start=persist_artifacts_stage_start,
                artifacts_created=_artifact_keys(stored_artifact_manifest),
                diagnostic_context={"artifact_count": len(stored_artifact_manifest.artifacts)},
            )
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
        _raise_stage_failure(
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
        summary = _append_whole_run_spectral_metadata(
            summary,
            spectral_result.coverage_summary,
            spectral_bundle=spectral_bundle,
        )
        summary = _append_run_context_warnings(summary, spectral_result.coverage_summary.warnings)
    if context_bundle is not None:
        summary = _append_whole_run_context(summary, context_bundle)

    analysis_payload = summary.to_json_object()
    analysis_metadata_payload = analysis_payload.get("analysis_metadata")
    analysis_metadata = (
        dict(analysis_metadata_payload) if isinstance(analysis_metadata_payload, dict) else {}
    )

    if order_trace_bundle is not None:
        summary = _append_whole_run_order_trace_metadata(summary, order_trace_bundle)
    if order_trace_summary_bundle is not None:
        summary = _append_whole_run_order_trace_summary_metadata(
            summary,
            order_trace_summary_bundle,
        )
    if order_family_summary_bundle is not None:
        summary = _append_whole_run_order_summaries(summary, order_family_summary_bundle)
        summary = _append_whole_run_order_family_summary_metadata(
            summary,
            order_family_summary_bundle,
        )
    if spatial_coherence_bundle is not None:
        summary = _append_whole_run_spatial_summaries(summary, spatial_coherence_bundle)
        summary = _append_whole_run_spatial_coherence_metadata(
            summary,
            spatial_coherence_bundle,
        )
    if context_bundle is not None and order_family_summary_bundle is not None:
        diagnosis_summaries = diagnosis_summary_builder(
            analysis_metadata=analysis_metadata,
            context_bundle=context_bundle,
            order_summaries=_ranked_whole_run_order_summaries(
                order_family_summary_bundle.summaries
            ),
            spatial_summaries=(
                _ranked_whole_run_spatial_summaries(spatial_coherence_bundle.summaries)
                if spatial_coherence_bundle is not None
                else ()
            ),
        )
        if diagnosis_summaries:
            summary = _append_whole_run_diagnosis_summaries(summary, diagnosis_summaries)
            summary = _append_whole_run_diagnosis_summary_metadata(
                summary,
                diagnosis_summaries,
            )
    if stored_artifact_manifest is not None:
        summary = _append_whole_run_analysis_metadata(summary, stored_artifact_manifest)

    return summary, _make_stage_result(
        stage_name=stage_name,
        status="ok",
        stage_start=stage_start,
        warnings=(
            _warning_codes(tuple(spectral_result.coverage_summary.warnings))
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
        _sync_call(db, "astore_analysis", run_id, summary)
    except (aiosqlite.Error, OSError, MemoryError) as exc:
        _raise_stage_failure(
            stage_name=stage_name,
            stage_start=stage_start,
            exc=exc,
            diagnostic_context={"run_id": run_id},
        )
    return _make_stage_result(
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
        _sync_call(db, "astore_analysis_error", run_id, completed_error)
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
        _sync_call(db, "astore_analysis_error", run_id, completed_error)
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


def _build_whole_run_artifacts(
    *,
    run_id: str,
    metadata: RunMetadata,
    raw_capture: RawRunCapture,
) -> WholeRunSpectralBuildResult:
    return build_whole_run_spectral_artifact_bundle(
        run_id=run_id,
        metadata=metadata,
        raw_capture=raw_capture,
    )


def _build_whole_run_context_artifacts(
    *,
    run: PostAnalysisRunInput,
    total_sample_count: int | None = None,
    window_plan: WholeRunWindowPlan | None = None,
) -> WholeRunContextArtifactBundle | None:
    if total_sample_count is not None and total_sample_count < 0:
        raise ValueError("whole-run context builder requires total_sample_count >= 0")
    return build_whole_run_context_artifact_bundle(
        run_id=run.run_id,
        metadata=run.context,
        samples=run.context_samples,
        total_sample_count=total_sample_count,
        window_plan=window_plan,
    )


def _whole_run_total_sample_count(manifest: RawCaptureManifest) -> int:
    if manifest.sensors:
        return max(int(sensor.sample_count) for sensor in manifest.sensors)
    return max(0, int(manifest.total_samples))


def _build_whole_run_order_trace_artifacts(
    *,
    run: PostAnalysisRunInput,
    spectral_bundle: WholeRunSpectralArtifactBundle,
    context_bundle: WholeRunContextArtifactBundle,
) -> WholeRunOrderTraceArtifactBundle | None:
    return build_whole_run_order_trace_artifact_bundle(
        run_id=run.run_id,
        metadata=run.context,
        spectral_manifest=spectral_bundle.manifest,
        spectral_artifact_contents=spectral_bundle.artifact_contents,
        context_labels=context_bundle.labels,
        samples=run.context_samples,
        lang=run.language,
    )


def _build_whole_run_order_trace_summary_artifacts(
    *,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle,
    context_bundle: WholeRunContextArtifactBundle,
) -> WholeRunOrderTraceSummaryArtifactBundle | None:
    return build_whole_run_order_trace_summary_artifact_bundle(
        order_trace_bundle=order_trace_bundle,
        context_labels=context_bundle.labels,
    )


def _build_whole_run_order_family_summary_artifacts(
    *,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle,
    order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle,
    context_bundle: WholeRunContextArtifactBundle,
) -> WholeRunOrderFamilySummaryArtifactBundle | None:
    return build_whole_run_order_family_summary_artifact_bundle(
        order_trace_bundle=order_trace_bundle,
        order_trace_summary_bundle=order_trace_summary_bundle,
        context_labels=context_bundle.labels,
    )


def _build_whole_run_spatial_coherence_artifacts(
    *,
    run: PostAnalysisRunInput,
    spectral_bundle: WholeRunSpectralArtifactBundle,
    context_bundle: WholeRunContextArtifactBundle,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle,
) -> WholeRunSpatialCoherenceArtifactBundle | None:
    if not order_trace_bundle.points:
        return None
    return build_whole_run_spatial_coherence_artifact_bundle(
        order_trace_bundle=order_trace_bundle,
        spectral_manifest=spectral_bundle.manifest,
        spectral_artifact_contents=spectral_bundle.artifact_contents,
        context_labels=context_bundle.labels,
        samples=run.samples,
        lang=run.language,
    )


def _merge_whole_run_artifact_bundles(
    *bundles: (
        WholeRunSpectralArtifactBundle
        | WholeRunContextArtifactBundle
        | WholeRunOrderTraceArtifactBundle
        | WholeRunOrderTraceSummaryArtifactBundle
        | WholeRunOrderFamilySummaryArtifactBundle
        | WholeRunSpatialCoherenceArtifactBundle
        | None
    ),
) -> _StoredWholeRunArtifactBundle | None:
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
    return _StoredWholeRunArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id=base_manifest.run_id,
            relative_dir=base_manifest.relative_dir,
            window_policy=base_manifest.window_policy,
            total_window_count=base_manifest.total_window_count,
            artifacts=tuple(merged_artifacts),
            created_at=base_manifest.created_at,
            schema_version=base_manifest.schema_version,
            storage_type=base_manifest.storage_type,
        ),
        artifact_contents=merged_contents,
    )


def _append_whole_run_analysis_metadata(
    summary: PersistedAnalysis,
    manifest: WholeRunArtifactManifest,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    sensor_ids = sorted(
        {artifact.sensor_id for artifact in manifest.artifacts if artifact.sensor_id is not None}
    )
    analysis_metadata["whole_run_artifacts_available"] = True
    analysis_metadata["whole_run_window_count"] = int(manifest.total_window_count)
    analysis_metadata["whole_run_sensor_count"] = len(sensor_ids)
    analysis_metadata["whole_run_artifact_count"] = len(manifest.artifacts)
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_spectral_metadata(
    summary: PersistedAnalysis,
    coverage_summary: WholeRunSpectralCoverageSummary,
    *,
    spectral_bundle: WholeRunSpectralArtifactBundle | None,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    analysis_metadata["whole_run_spectral_available"] = spectral_bundle is not None
    analysis_metadata["whole_run_spectral_window_count"] = (
        spectral_bundle.manifest.total_window_count if spectral_bundle is not None else 0
    )
    analysis_metadata["whole_run_spectral_sensor_window_count"] = (
        coverage_summary.total_sensor_window_count
    )
    analysis_metadata["whole_run_spectral_full_sensor_window_count"] = (
        coverage_summary.full_sensor_window_count
    )
    analysis_metadata["whole_run_spectral_partial_sensor_window_count"] = (
        coverage_summary.partial_sensor_window_count
    )
    analysis_metadata["whole_run_spectral_missing_sensor_window_count"] = (
        coverage_summary.missing_sensor_window_count
    )
    analysis_metadata["whole_run_spectral_empty_sensor_window_count"] = (
        coverage_summary.empty_sensor_window_count
    )
    analysis_metadata["whole_run_spectral_gap_count"] = coverage_summary.gap_count
    analysis_metadata["whole_run_spectral_overlap_count"] = coverage_summary.overlap_count
    analysis_metadata["whole_run_spectral_dropped_chunk_count"] = (
        coverage_summary.dropped_chunk_count
    )
    analysis_metadata["whole_run_spectral_late_packet_chunk_count"] = getattr(
        coverage_summary, "late_packet_chunk_count", 0
    )
    analysis_metadata["whole_run_spectral_udp_ingest_queue_drop_count"] = getattr(
        coverage_summary, "udp_ingest_queue_drop_count", 0
    )
    analysis_metadata["whole_run_spectral_queue_overflow_chunk_count"] = (
        coverage_summary.queue_overflow_chunk_count
    )
    analysis_metadata["whole_run_spectral_invalid_chunk_count"] = (
        coverage_summary.invalid_chunk_count
    )
    analysis_metadata["whole_run_spectral_write_error_chunk_count"] = (
        coverage_summary.write_error_chunk_count
    )
    analysis_metadata["whole_run_spectral_sample_rate_mismatch_sensor_count"] = (
        coverage_summary.sample_rate_mismatch_sensor_count
    )
    analysis_metadata["whole_run_spectral_sample_rate_unverified_sensor_count"] = (
        coverage_summary.sample_rate_unverified_sensor_count
    )
    analysis_metadata["whole_run_spectral_unanchored_sensor_count"] = (
        coverage_summary.unanchored_sensor_count
    )
    analysis_metadata["whole_run_spectral_legacy_sensor_count"] = (
        coverage_summary.legacy_sensor_count
    )
    analysis_metadata["whole_run_spectral_sync_unverified_sensor_count"] = (
        coverage_summary.sync_unverified_sensor_count
    )
    analysis_metadata["whole_run_spectral_stale_sync_sensor_count"] = (
        coverage_summary.stale_sync_sensor_count
    )
    analysis_metadata["whole_run_spectral_high_rtt_sensor_count"] = (
        coverage_summary.high_rtt_sensor_count
    )
    analysis_metadata["whole_run_spectral_coverage_confidence"] = (
        coverage_summary.coverage_confidence
    )
    return PersistedAnalysis.from_json_object(payload)


def _append_run_context_warnings(
    summary: PersistedAnalysis,
    warnings: RunContextWarningsInput,
) -> PersistedAnalysis:
    if not warnings:
        return summary
    payload = summary.to_json_object()
    existing = payload.get("warnings")
    warnings_payload: list[JsonValue] = []
    if isinstance(existing, list):
        warnings_payload.extend(item for item in existing if is_json_object(item))
    for warning in normalize_run_context_warnings(warnings):
        warning_payload: JsonObject = {
            "code": warning.code,
            "severity": warning.severity,
            "applies_to": warning.applies_to,
            "title": warning.title,
            "detail": warning.detail,
        }
        warnings_payload.append(warning_payload)
    payload["warnings"] = warnings_payload
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_context(
    summary: PersistedAnalysis,
    bundle: WholeRunContextArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    payload["whole_run_context_intervals"] = [
        interval.to_json_object() for interval in bundle.intervals
    ]
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    analysis_metadata["whole_run_context_available"] = True
    analysis_metadata["whole_run_context_window_count"] = int(bundle.manifest.total_window_count)
    analysis_metadata["whole_run_context_interval_count"] = len(bundle.intervals)
    analysis_metadata["whole_run_context_full_window_count"] = sum(
        1 for label in bundle.labels if label.context_coverage == "full"
    )
    analysis_metadata["whole_run_context_partial_window_count"] = sum(
        1 for label in bundle.labels if label.context_coverage == "partial"
    )
    analysis_metadata["whole_run_context_missing_window_count"] = sum(
        1 for label in bundle.labels if label.context_coverage == "missing"
    )
    analysis_metadata["whole_run_context_missing_speed_window_count"] = sum(
        1 for label in bundle.labels if label.speed_validity == "missing"
    )
    analysis_metadata["whole_run_context_missing_rpm_window_count"] = sum(
        1 for label in bundle.labels if label.rpm_validity == "missing"
    )
    analysis_metadata["whole_run_context_stale_speed_window_count"] = sum(
        1 for label in bundle.labels if label.speed_is_stale
    )
    analysis_metadata["whole_run_context_stale_rpm_window_count"] = sum(
        1 for label in bundle.labels if label.rpm_is_stale
    )
    analysis_metadata["whole_run_context_labels_artifact_key"] = (
        WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY
    )
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_order_trace_metadata(
    summary: PersistedAnalysis,
    bundle: WholeRunOrderTraceArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    analysis_metadata["whole_run_order_traces_available"] = True
    analysis_metadata["whole_run_order_trace_point_count"] = len(bundle.points)
    analysis_metadata["whole_run_order_trace_candidate_count"] = len(
        {point.hypothesis_key for point in bundle.points}
    )
    analysis_metadata["whole_run_order_trace_artifact_key"] = WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_order_trace_summary_metadata(
    summary: PersistedAnalysis,
    bundle: WholeRunOrderTraceSummaryArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    analysis_metadata["whole_run_order_trace_summaries_available"] = True
    analysis_metadata["whole_run_order_trace_summary_count"] = len(bundle.summaries)
    analysis_metadata["whole_run_order_trace_summary_artifact_key"] = (
        WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY
    )
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_order_family_summary_metadata(
    summary: PersistedAnalysis,
    bundle: WholeRunOrderFamilySummaryArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    analysis_metadata["whole_run_order_family_summaries_available"] = True
    analysis_metadata["whole_run_order_family_summary_count"] = len(bundle.summaries)
    analysis_metadata["whole_run_order_family_summary_artifact_key"] = (
        WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY
    )
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_spatial_coherence_metadata(
    summary: PersistedAnalysis,
    bundle: WholeRunSpatialCoherenceArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    analysis_metadata["whole_run_spatial_coherence_available"] = True
    analysis_metadata["whole_run_spatial_coherence_window_count"] = len(bundle.windows)
    analysis_metadata["whole_run_spatial_coherence_candidate_count"] = len(
        {row.candidate_key for row in bundle.windows}
    )
    analysis_metadata["whole_run_spatial_coherence_summary_count"] = len(bundle.summaries)
    analysis_metadata["whole_run_spatial_coherence_artifact_key"] = (
        WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY
    )
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_order_summaries(
    summary: PersistedAnalysis,
    bundle: WholeRunOrderFamilySummaryArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    payload["whole_run_order_summaries"] = [
        row.to_json_object() for row in _ranked_whole_run_order_summaries(bundle.summaries)
    ]
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_spatial_summaries(
    summary: PersistedAnalysis,
    bundle: WholeRunSpatialCoherenceArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    payload["whole_run_spatial_summaries"] = [
        row.to_json_object() for row in _ranked_whole_run_spatial_summaries(bundle.summaries)
    ]
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_diagnosis_summaries(
    summary: PersistedAnalysis,
    diagnosis_summaries: tuple[WholeRunDiagnosisSummary, ...],
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    payload["whole_run_diagnosis_summaries"] = [row.to_json_object() for row in diagnosis_summaries]
    return PersistedAnalysis.from_json_object(payload)


def _append_whole_run_diagnosis_summary_metadata(
    summary: PersistedAnalysis,
    diagnosis_summaries: tuple[WholeRunDiagnosisSummary, ...],
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    analysis_metadata["whole_run_diagnosis_summaries_available"] = True
    analysis_metadata["whole_run_diagnosis_summary_count"] = len(diagnosis_summaries)
    return PersistedAnalysis.from_json_object(payload)


def _build_whole_run_diagnosis_summaries(
    *,
    analysis_metadata: Mapping[str, object],
    context_bundle: WholeRunContextArtifactBundle,
    order_summaries: tuple[OrderTraceSummary, ...],
    spatial_summaries: tuple[SpatialEvidenceSummary, ...],
) -> tuple[WholeRunDiagnosisSummary, ...]:
    return build_whole_run_diagnosis_summaries(
        analysis_metadata=analysis_metadata,
        context_intervals=context_bundle.intervals,
        order_summaries=order_summaries,
        spatial_summaries=spatial_summaries,
    )


def _ranked_whole_run_order_summaries(
    summaries: tuple[OrderTraceSummary, ...],
) -> tuple[OrderTraceSummary, ...]:
    return tuple(
        sorted(
            summaries,
            key=lambda summary: (
                -summary.lock_score,
                -summary.matched_window_count,
                -summary.support_ratio,
                -(summary.peak_intensity_db if summary.peak_intensity_db is not None else -1.0),
                -summary.reference_coverage_ratio,
                summary.hypothesis_key,
            ),
        )
    )


def _ranked_whole_run_spatial_summaries(
    summaries: tuple[SpatialEvidenceSummary, ...],
) -> tuple[SpatialEvidenceSummary, ...]:
    return tuple(
        sorted(
            summaries,
            key=lambda summary: (
                -summary.coherent_window_count,
                -summary.supporting_window_count,
                -(summary.coherence_ratio if summary.coherence_ratio is not None else -1.0),
                -(
                    summary.location_separation_db
                    if summary.location_separation_db is not None
                    else -1.0
                ),
                -(summary.dominance_ratio if summary.dominance_ratio is not None else -1.0),
                summary.candidate_key,
            ),
        )
    )
