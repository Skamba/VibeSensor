"""Post-analysis execution for one completed run, as straight-line steps.

``execute_post_analysis`` runs these steps in order and logs one structured
``post_analysis_step`` line per step (status ``ok``/``skipped``/``degraded``/
``failed`` plus timing and step details):

1. ``load_run`` loads metadata and summary rows. Missing metadata or an empty
   run ends the attempt with a stored terminal error.
2. ``build_input`` shapes the canonical ``PostAnalysisRunInput``.
3. Whole-run sidecar steps: ``whole_run_spectra``, ``whole_run_context``,
   ``order_traces``, ``order_trace_summary``, ``order_family_summary``,
   ``spatial_summary`` and ``persist_whole_run_artifacts``. Each is skipped
   when its raw-capture or upstream-bundle prerequisites are missing.
4. ``report_facts`` runs the sample-based analysis and folds the whole-run
   facts into the persisted analysis.
5. ``persist_analysis`` stores the persisted analysis.

A storage or memory error (``sqlite3.Error``, ``OSError``, ``MemoryError``)
or a run too short for strength metrics aborts the sequence. The error is
either deferred for a retry or stored as the run's analysis error.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from opentelemetry.trace import SpanKind

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.shared.types.json_types import JsonObject, JsonValue
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
_STEP_ERRORS = (sqlite3.Error, OSError, MemoryError, MissingStrengthMetricsError)


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
class WholeRunArtifacts:
    """Bundles built by the whole-run sidecar steps (``None`` when skipped)."""

    stored_manifest: WholeRunArtifactManifest | None = None
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
            with _step(run_id, "load_run") as step:
                load_result = config.load_run(run_id=run_id, db=db)
                if isinstance(load_result, MissingPostAnalysisMetadata | EmptyPostAnalysisSamples):
                    failure_kind = (
                        "missing_metadata"
                        if isinstance(load_result, MissingPostAnalysisMetadata)
                        else "no_samples"
                    )
                    step.update(status="failed", failure_kind=failure_kind)
                else:
                    step.update(
                        sample_count=len(load_result.samples),
                        raw_capture_available=load_result.raw_capture is not None,
                        raw_capture_manifest_available=(
                            load_result.raw_capture_manifest is not None
                        ),
                    )
            if isinstance(load_result, MissingPostAnalysisMetadata | EmptyPostAnalysisSamples):
                span.set_attribute("vibesensor.failure_kind", failure_kind)
                return _store_load_error(
                    db=db,
                    run_id=run_id,
                    completed_error=load_result.error_message,
                    kind=failure_kind,
                )
            loaded = load_result

            with _step(run_id, "build_input") as step:
                run_input = build_post_analysis_input(loaded)
                step.update(
                    summary_row_count=len(run_input.samples),
                    raw_capture_available=run_input.raw_capture_available,
                    sampling_method=run_input.sampling_method,
                )

            artifacts = build_whole_run_artifacts(db=db, loaded=loaded, run_input=run_input)
            summary = build_report_facts(
                run_input=run_input,
                analysis_runner=config.analysis_runner,
                artifacts=artifacts,
            )
            with _step(run_id, "persist_analysis"):
                db.store_analysis(loaded.run_id, summary)
        except _STEP_ERRORS as exc:
            mark_span_error(span, exc)
            if config.defer_retryable_error_storage and is_retryable_post_analysis_error(exc):
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


# ---------------------------------------------------------------------------
# Step logging and persistence bridge
# ---------------------------------------------------------------------------


@contextmanager
def _step(run_id: str, step_name: str) -> Iterator[JsonObject]:
    """Time one step and log it once on exit.

    The body records ``status`` (default ``ok``) and step details in the yielded
    dict. An exception is logged as ``failed`` and re-raised.
    """
    details: JsonObject = {"status": "ok"}
    step_start = time.monotonic()
    try:
        yield details
    except BaseException as exc:
        details["status"] = "failed"
        details["error_message"] = str(exc)
        raise
    finally:
        status = str(details.pop("status"))
        duration_ms = max(0, int(round((time.monotonic() - step_start) * 1000)))
        log_fn = LOGGER.warning if status in {"degraded", "failed"} else LOGGER.info
        log_fn(
            "Post-analysis step %s for run %s: %s (%d ms)",
            step_name,
            run_id,
            status,
            duration_ms,
            extra=log_extra(
                event="post_analysis_step",
                run_id=run_id,
                step=step_name,
                step_status=status,
                duration_ms=duration_ms,
                details=details,
            ),
        )


def _record_bundle(details: JsonObject, manifest: WholeRunArtifactManifest | None) -> None:
    """Record a built bundle's artifact keys, or mark the step skipped when none was built."""
    if manifest is None:
        details.update(status="skipped", reason="builder_returned_none")
        return
    details["artifacts"] = [item.artifact_key for item in manifest.artifacts]


def _warning_codes(warnings: tuple[object, ...]) -> list[JsonValue]:
    return [code for warning in warnings if isinstance(code := getattr(warning, "code", None), str)]


# ---------------------------------------------------------------------------
# Whole-run sidecar steps
# ---------------------------------------------------------------------------


def build_whole_run_artifacts(
    *,
    db: RunPersistence,
    loaded: LoadedPostAnalysisRun,
    run_input: PostAnalysisRunInput,
) -> WholeRunArtifacts:
    """Build, then persist, the dense whole-run sidecar artifacts for one run."""
    run_id = loaded.run_id
    policy = assess_whole_run_raw_capture_policy(loaded)

    spectral_result = _build_spectra(db=db, loaded=loaded, policy=policy)
    spectral_bundle = spectral_result.bundle if spectral_result is not None else None
    context_bundle = _build_context(
        run_id=run_id,
        run_input=run_input,
        policy=policy,
        spectral_result=spectral_result,
    )

    order_trace_bundle: WholeRunOrderTraceArtifactBundle | None = None
    with _step(run_id, "order_traces") as step:
        if spectral_bundle is None or context_bundle is None:
            step.update(status="skipped", reason="missing_prerequisites")
        else:
            order_trace_bundle = build_whole_run_order_trace_artifact_bundle(
                run_id=run_input.run_id,
                metadata=run_input.context,
                spectral_manifest=spectral_bundle.manifest,
                spectral_artifact_contents=spectral_bundle.artifact_contents,
                context_labels=context_bundle.labels,
                samples=run_input.context_samples,
                lang=run_input.language,
            )
            _record_bundle(step, order_trace_bundle.manifest if order_trace_bundle else None)

    order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle | None = None
    with _step(run_id, "order_trace_summary") as step:
        if order_trace_bundle is None or context_bundle is None:
            step.update(status="skipped", reason="missing_prerequisites")
        else:
            order_trace_summary_bundle = build_whole_run_order_trace_summary_artifact_bundle(
                order_trace_bundle=order_trace_bundle,
                context_labels=context_bundle.labels,
            )
            _record_bundle(
                step,
                order_trace_summary_bundle.manifest if order_trace_summary_bundle else None,
            )

    order_family_summary_bundle: WholeRunOrderFamilySummaryArtifactBundle | None = None
    with _step(run_id, "order_family_summary") as step:
        if (
            order_trace_bundle is None
            or order_trace_summary_bundle is None
            or context_bundle is None
        ):
            step.update(status="skipped", reason="missing_prerequisites")
        else:
            order_family_summary_bundle = build_whole_run_order_family_summary_artifact_bundle(
                order_trace_bundle=order_trace_bundle,
                order_trace_summary_bundle=order_trace_summary_bundle,
                context_labels=context_bundle.labels,
            )
            _record_bundle(
                step,
                order_family_summary_bundle.manifest if order_family_summary_bundle else None,
            )

    spatial_coherence_bundle: WholeRunSpatialCoherenceArtifactBundle | None = None
    with _step(run_id, "spatial_summary") as step:
        if spectral_bundle is None or context_bundle is None or order_trace_bundle is None:
            step.update(status="skipped", reason="missing_prerequisites")
        else:
            # Spatial coherence is only defined over order-trace points.
            if order_trace_bundle.points:
                spatial_coherence_bundle = build_whole_run_spatial_coherence_artifact_bundle(
                    order_trace_bundle=order_trace_bundle,
                    spectral_manifest=spectral_bundle.manifest,
                    spectral_artifact_contents=spectral_bundle.artifact_contents,
                    context_labels=context_bundle.labels,
                    samples=run_input.samples,
                    lang=run_input.language,
                )
            _record_bundle(
                step,
                spatial_coherence_bundle.manifest if spatial_coherence_bundle else None,
            )

    stored_manifest: WholeRunArtifactManifest | None = None
    with _step(run_id, "persist_whole_run_artifacts") as step:
        merged_bundle = merge_whole_run_artifact_bundles(
            spectral_bundle,
            context_bundle,
            order_trace_bundle,
            order_trace_summary_bundle,
            order_family_summary_bundle,
            spatial_coherence_bundle,
        )
        if merged_bundle is None:
            step.update(status="skipped", reason="no_artifacts_to_persist")
        else:
            stored_manifest = db.store_whole_run_artifacts(
                run_id,
                merged_bundle.manifest,
                artifact_contents=merged_bundle.artifact_contents,
            )
            if stored_manifest is None:
                raise OSError(f"Failed to persist whole-run artifacts for run {run_id}")
            _record_bundle(step, stored_manifest)

    return WholeRunArtifacts(
        stored_manifest=stored_manifest,
        spectral_result=spectral_result,
        spectral_bundle=spectral_bundle,
        context_bundle=context_bundle,
        order_trace_bundle=order_trace_bundle,
        order_trace_summary_bundle=order_trace_summary_bundle,
        order_family_summary_bundle=order_family_summary_bundle,
        spatial_coherence_bundle=spatial_coherence_bundle,
    )


def _build_spectra(
    *,
    db: RunPersistence,
    loaded: LoadedPostAnalysisRun,
    policy: WholeRunRawCapturePolicy,
) -> WholeRunSpectralBuildResult | None:
    with _step(loaded.run_id, "whole_run_spectra") as step:
        if not policy.raw_capture_prerequisites_met():
            step.update(status="skipped", reason=policy.raw_capture_skip_reason())
            return None
        raw_capture_manifest = policy.manifest
        assert raw_capture_manifest is not None
        result = build_whole_run_spectral_artifact_bundle_from_ranges(
            run_id=loaded.run_id,
            metadata=loaded.metadata,
            raw_capture_manifest=raw_capture_manifest,
            raw_range_reader=_raw_range_reader(db, loaded),
        )
        step.update(
            artifacts=(
                [item.artifact_key for item in result.bundle.manifest.artifacts]
                if result.bundle is not None
                else []
            ),
            warnings=_warning_codes(tuple(result.coverage_summary.warnings)),
            bundle_available=result.bundle is not None,
            coverage_confidence=result.coverage_summary.coverage_confidence,
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


def _build_context(
    *,
    run_id: str,
    run_input: PostAnalysisRunInput,
    policy: WholeRunRawCapturePolicy,
    spectral_result: WholeRunSpectralBuildResult | None,
) -> WholeRunContextArtifactBundle | None:
    with _step(run_id, "whole_run_context") as step:
        if not policy.raw_capture_prerequisites_met():
            step.update(status="skipped", reason=policy.raw_capture_skip_reason())
            return None
        raw_capture_manifest = policy.manifest
        assert raw_capture_manifest is not None
        # Prefer the spectral window plan so context labels align with the spectra;
        # otherwise plan windows from the raw sample count (reported as degraded).
        window_plan = spectral_result.window_plan if spectral_result is not None else None
        total_sample_count: int | None = None
        step["build_mode"] = "window_plan"
        if window_plan is None:
            step.update(status="degraded", build_mode="total_sample_count_fallback")
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
        _record_bundle(step, bundle.manifest if bundle is not None else None)
        return bundle


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
# Report facts
# ---------------------------------------------------------------------------


def build_report_facts(
    *,
    run_input: PostAnalysisRunInput,
    analysis_runner: PostAnalysisRunner,
    artifacts: WholeRunArtifacts,
) -> PersistedAnalysis:
    """Run the sample-based analysis and fold the whole-run facts into it."""
    with _step(run_input.run_id, "report_facts") as step:
        raw_summary = analysis_runner(run_input)
        summary = (
            raw_summary
            if isinstance(raw_summary, PersistedAnalysis)
            else PersistedAnalysis.from_json_object(raw_summary)
        )

        spectral_result = artifacts.spectral_result
        context_bundle = artifacts.context_bundle
        order_trace_bundle = artifacts.order_trace_bundle
        order_trace_summary_bundle = artifacts.order_trace_summary_bundle
        order_family_summary_bundle = artifacts.order_family_summary_bundle
        spatial_coherence_bundle = artifacts.spatial_coherence_bundle
        stored_artifact_manifest = artifacts.stored_manifest

        if spectral_result is not None:
            summary = append_whole_run_spectral_metadata(
                summary,
                spectral_result.coverage_summary,
                spectral_bundle=artifacts.spectral_bundle,
            )
            summary = append_run_context_warnings(
                summary, spectral_result.coverage_summary.warnings
            )
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
                order_summaries=ranked_whole_run_order_summaries(
                    order_family_summary_bundle.summaries
                ),
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

        step.update(
            whole_run_artifacts_available=stored_artifact_manifest is not None,
            whole_run_context_available=context_bundle is not None,
            whole_run_order_family_available=order_family_summary_bundle is not None,
            whole_run_spatial_available=spatial_coherence_bundle is not None,
        )
        return refresh_report_fallback_metadata(summary)


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
    except sqlite3.Error as store_exc:
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
