"""Execution and persistence coordination for background post-analysis."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

import aiosqlite
from opentelemetry.trace import SpanKind

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawCaptureSensorRange
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
    build_whole_run_spectral_artifact_bundle,
)
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
        raw_capture_manifest: RawCaptureManifest,
        db: RunPersistence,
    ) -> WholeRunSpectralArtifactBundle | None: ...


class WholeRunContextBuilder(Protocol):
    """Injected boundary for building dense whole-run context sidecars."""

    def __call__(
        self,
        *,
        run: PostAnalysisRunInput,
        total_sample_count: int,
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
    resolved_whole_run_artifact_builder = (
        _build_whole_run_artifacts
        if whole_run_artifact_builder is None
        else whole_run_artifact_builder
    )
    resolved_whole_run_context_builder = (
        _build_whole_run_context_artifacts
        if whole_run_context_builder is None
        else whole_run_context_builder
    )
    resolved_whole_run_order_trace_builder = (
        _build_whole_run_order_trace_artifacts
        if whole_run_order_trace_builder is None
        else whole_run_order_trace_builder
    )
    resolved_whole_run_order_trace_summary_builder = (
        _build_whole_run_order_trace_summary_artifacts
        if whole_run_order_trace_summary_builder is None
        else whole_run_order_trace_summary_builder
    )
    resolved_whole_run_order_family_summary_builder = (
        _build_whole_run_order_family_summary_artifacts
        if whole_run_order_family_summary_builder is None
        else whole_run_order_family_summary_builder
    )
    resolved_whole_run_spatial_coherence_builder = (
        _build_whole_run_spatial_coherence_artifacts
        if whole_run_spatial_coherence_builder is None
        else whole_run_spatial_coherence_builder
    )
    resolved_whole_run_diagnosis_summary_builder = (
        _build_whole_run_diagnosis_summaries
        if whole_run_diagnosis_summary_builder is None
        else whole_run_diagnosis_summary_builder
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
        try:
            run_input = build_post_analysis_input(loaded)
            stored_artifact_manifest: WholeRunArtifactManifest | None = None
            context_bundle: WholeRunContextArtifactBundle | None = None
            order_trace_bundle: WholeRunOrderTraceArtifactBundle | None = None
            order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle | None = None
            order_family_summary_bundle: WholeRunOrderFamilySummaryArtifactBundle | None = None
            spatial_coherence_bundle: WholeRunSpatialCoherenceArtifactBundle | None = None
            if loaded.raw_capture_manifest is not None:
                spectral_bundle = resolved_whole_run_artifact_builder(
                    run_id=loaded.run_id,
                    metadata=loaded.metadata,
                    raw_capture_manifest=loaded.raw_capture_manifest,
                    db=db,
                )
                context_bundle = resolved_whole_run_context_builder(
                    run=run_input,
                    total_sample_count=_whole_run_total_sample_count(loaded.raw_capture_manifest),
                )
                if spectral_bundle is not None and context_bundle is not None:
                    order_trace_bundle = resolved_whole_run_order_trace_builder(
                        run=run_input,
                        spectral_bundle=spectral_bundle,
                        context_bundle=context_bundle,
                    )
                if order_trace_bundle is not None and context_bundle is not None:
                    order_trace_summary_bundle = resolved_whole_run_order_trace_summary_builder(
                        order_trace_bundle=order_trace_bundle,
                        context_bundle=context_bundle,
                    )
                if (
                    order_trace_bundle is not None
                    and order_trace_summary_bundle is not None
                    and context_bundle is not None
                ):
                    order_family_summary_bundle = resolved_whole_run_order_family_summary_builder(
                        order_trace_bundle=order_trace_bundle,
                        order_trace_summary_bundle=order_trace_summary_bundle,
                        context_bundle=context_bundle,
                    )
                if (
                    spectral_bundle is not None
                    and context_bundle is not None
                    and order_trace_bundle is not None
                ):
                    spatial_coherence_bundle = resolved_whole_run_spatial_coherence_builder(
                        run=run_input,
                        spectral_bundle=spectral_bundle,
                        context_bundle=context_bundle,
                        order_trace_bundle=order_trace_bundle,
                    )
                merged_bundle = _merge_whole_run_artifact_bundles(
                    spectral_bundle,
                    context_bundle,
                    order_trace_bundle,
                    order_trace_summary_bundle,
                    order_family_summary_bundle,
                    spatial_coherence_bundle,
                )
                if merged_bundle is not None:
                    stored_artifact_manifest = _sync_call(
                        db,
                        "astore_whole_run_artifacts",
                        loaded.run_id,
                        merged_bundle.manifest,
                        artifact_contents=merged_bundle.artifact_contents,
                    )
                    if stored_artifact_manifest is None:
                        raise OSError(
                            f"Failed to persist whole-run artifacts for run {loaded.run_id}"
                        )
            span.set_attribute("vibesensor.sample_count", len(run_input.samples))
            summary = _coerce_persisted_analysis(analysis_runner(run_input))
            if context_bundle is not None:
                summary = _append_whole_run_context(summary, context_bundle)
            analysis_payload = summary.to_json_object()
            analysis_metadata_payload = analysis_payload.get("analysis_metadata")
            analysis_metadata = (
                dict(analysis_metadata_payload)
                if isinstance(analysis_metadata_payload, dict)
                else {}
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
            if order_family_summary_bundle is not None:
                summary = _append_whole_run_order_family_summary_metadata(
                    summary,
                    order_family_summary_bundle,
                )
            if spatial_coherence_bundle is not None:
                summary = _append_whole_run_spatial_summaries(
                    summary,
                    spatial_coherence_bundle,
                )
            if spatial_coherence_bundle is not None:
                summary = _append_whole_run_spatial_coherence_metadata(
                    summary,
                    spatial_coherence_bundle,
                )
            if context_bundle is not None and order_family_summary_bundle is not None:
                diagnosis_summaries = resolved_whole_run_diagnosis_summary_builder(
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
            _sync_call(db, "astore_analysis", loaded.run_id, summary)
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
    raw_capture_manifest: RawCaptureManifest,
    db: RunPersistence,
) -> WholeRunSpectralArtifactBundle | None:
    def load_sensor_range(
        *,
        client_id: str,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None:
        return cast(
            RawCaptureSensorRange | None,
            _sync_call(
                db,
                "aload_raw_capture_sensor_range",
                run_id,
                client_id,
                sample_start=sample_start,
                sample_count=sample_count,
            ),
        )

    return build_whole_run_spectral_artifact_bundle(
        run_id=run_id,
        metadata=metadata,
        raw_capture_manifest=raw_capture_manifest,
        load_sensor_range=load_sensor_range,
    )


def _build_whole_run_context_artifacts(
    *,
    run: PostAnalysisRunInput,
    total_sample_count: int,
) -> WholeRunContextArtifactBundle | None:
    if total_sample_count < 0:
        raise ValueError("whole-run context builder requires total_sample_count >= 0")
    return build_whole_run_context_artifact_bundle(
        run_id=run.run_id,
        metadata=run.context,
        samples=run.context_samples,
        total_sample_count=total_sample_count,
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
