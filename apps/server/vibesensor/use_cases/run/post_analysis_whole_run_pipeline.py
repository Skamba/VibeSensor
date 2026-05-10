"""Whole-run sidecar pipeline stages for post-analysis."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import aiosqlite

from vibesensor.domain import CarOrderReferenceStatus
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.raw_capture import RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTraceSummary
from vibesensor.use_cases.diagnostics.orders.whole_run_family_summaries import (
    WholeRunOrderFamilySummaryArtifactBundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WholeRunOrderTraceSummaryArtifactBundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WholeRunOrderTraceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WholeRunContextArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_contracts import (
    WholeRunDiagnosisSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_coherence import (
    WholeRunSpatialCoherenceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunSpectralArtifactBundle,
    WholeRunSpectralBuildResult,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import WholeRunWindowPlan
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_raw_capture_policy import (
    WholeRunRawCapturePolicy,
    assess_whole_run_raw_capture_policy,
)
from vibesensor.use_cases.run.post_analysis_stage_runner import (
    PostAnalysisStageResult,
    PostAnalysisStageStatus,
    make_stage_result,
    raise_stage_failure,
    sync_run_persistence_call,
    warning_codes,
)
from vibesensor.use_cases.run.post_analysis_whole_run_builders import (
    StoredWholeRunArtifactBundle,
    build_whole_run_artifacts,
    build_whole_run_context_artifacts,
    build_whole_run_order_family_summary_artifacts,
    build_whole_run_order_trace_artifacts,
    build_whole_run_order_trace_summary_artifacts,
    build_whole_run_spatial_coherence_artifacts,
    merge_whole_run_artifact_bundles,
    whole_run_total_sample_count,
)
from vibesensor.use_cases.run.post_analysis_whole_run_projection import (
    build_diagnosis_summary_rows,
)


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
        car_order_reference_status: CarOrderReferenceStatus | None,
    ) -> tuple[WholeRunDiagnosisSummary, ...]: ...


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
class WholeRunStageExecution[ResultT]:
    """Stage runner payload before conversion into a public stage result."""

    result: ResultT
    status: PostAnalysisStageStatus
    artifact_manifest: WholeRunArtifactManifest | None = None
    warnings: tuple[str, ...] = ()
    diagnostic_context: JsonObject = field(default_factory=dict)


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


@dataclass(frozen=True, slots=True)
class WholeRunPipelineContext:
    db: RunPersistence
    loaded: LoadedPostAnalysisRun
    run_input: PostAnalysisRunInput
    builders: ResolvedWholeRunBuilders
    raw_capture_policy: WholeRunRawCapturePolicy


@dataclass(slots=True)
class WholeRunPipelineState:
    stage_results: list[PostAnalysisStageResult] = field(default_factory=list)
    stored_artifact_manifest: WholeRunArtifactManifest | None = None
    spectral_result: WholeRunSpectralBuildResult | None = None
    spectral_bundle: WholeRunSpectralArtifactBundle | None = None
    context_bundle: WholeRunContextArtifactBundle | None = None
    order_trace_bundle: WholeRunOrderTraceArtifactBundle | None = None
    order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle | None = None
    order_family_summary_bundle: WholeRunOrderFamilySummaryArtifactBundle | None = None
    spatial_coherence_bundle: WholeRunSpatialCoherenceArtifactBundle | None = None

    def output(self) -> WholeRunPipelineStageOutput:
        return WholeRunPipelineStageOutput(
            stage_results=tuple(self.stage_results),
            stored_artifact_manifest=self.stored_artifact_manifest,
            spectral_result=self.spectral_result,
            spectral_bundle=self.spectral_bundle,
            context_bundle=self.context_bundle,
            order_trace_bundle=self.order_trace_bundle,
            order_trace_summary_bundle=self.order_trace_summary_bundle,
            order_family_summary_bundle=self.order_family_summary_bundle,
            spatial_coherence_bundle=self.spatial_coherence_bundle,
        )


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
            build_whole_run_artifacts
            if whole_run_artifact_builder is None
            else whole_run_artifact_builder
        ),
        context_builder=(
            build_whole_run_context_artifacts
            if whole_run_context_builder is None
            else whole_run_context_builder
        ),
        order_trace_builder=(
            build_whole_run_order_trace_artifacts
            if whole_run_order_trace_builder is None
            else whole_run_order_trace_builder
        ),
        order_trace_summary_builder=(
            build_whole_run_order_trace_summary_artifacts
            if whole_run_order_trace_summary_builder is None
            else whole_run_order_trace_summary_builder
        ),
        order_family_summary_builder=(
            build_whole_run_order_family_summary_artifacts
            if whole_run_order_family_summary_builder is None
            else whole_run_order_family_summary_builder
        ),
        spatial_coherence_builder=(
            build_whole_run_spatial_coherence_artifacts
            if whole_run_spatial_coherence_builder is None
            else whole_run_spatial_coherence_builder
        ),
        diagnosis_summary_builder=(
            build_diagnosis_summary_rows
            if whole_run_diagnosis_summary_builder is None
            else whole_run_diagnosis_summary_builder
        ),
    )


def run_whole_run_pipeline_stages(
    *,
    db: RunPersistence,
    loaded: LoadedPostAnalysisRun,
    run_input: PostAnalysisRunInput,
    builders: ResolvedWholeRunBuilders,
) -> WholeRunPipelineStageOutput:
    context = WholeRunPipelineContext(
        db=db,
        loaded=loaded,
        run_input=run_input,
        builders=builders,
        raw_capture_policy=assess_whole_run_raw_capture_policy(loaded),
    )
    return WholeRunPipelineRunner(context).run()


def _artifact_keys(manifest: WholeRunArtifactManifest | None) -> tuple[str, ...]:
    if manifest is None:
        return ()
    return tuple(artifact.artifact_key for artifact in manifest.artifacts)


def _bundle_artifact_manifest(bundle: object | None) -> WholeRunArtifactManifest | None:
    manifest = getattr(bundle, "manifest", None)
    return manifest if isinstance(manifest, WholeRunArtifactManifest) else None


def _stage_execution[ResultT](
    result: ResultT | None,
    *,
    artifact_manifest: WholeRunArtifactManifest | None = None,
    status_when_present: PostAnalysisStageStatus = "ok",
    status_when_none: PostAnalysisStageStatus = "skipped",
    warnings: tuple[str, ...] = (),
    present_diagnostic_context: JsonObject | None = None,
    none_reason: str = "builder_returned_none",
    none_diagnostic_context: JsonObject | None = None,
) -> WholeRunStageExecution[ResultT | None]:
    if result is None:
        diagnostic_context: JsonObject = {"reason": none_reason}
        if none_diagnostic_context is not None:
            diagnostic_context = {**none_diagnostic_context, **diagnostic_context}
        return WholeRunStageExecution(
            result=None,
            status=status_when_none,
            warnings=warnings,
            diagnostic_context=diagnostic_context,
        )
    return WholeRunStageExecution(
        result=result,
        status=status_when_present,
        artifact_manifest=artifact_manifest,
        warnings=warnings,
        diagnostic_context={} if present_diagnostic_context is None else present_diagnostic_context,
    )


class WholeRunPipelineRunner:
    def __init__(self, context: WholeRunPipelineContext) -> None:
        self.context = context
        self.state = WholeRunPipelineState()

    def run(self) -> WholeRunPipelineStageOutput:
        self._run_spectral_stage()
        self._run_context_stage()
        self._run_order_trace_stage()
        self._run_order_trace_summary_stage()
        self._run_order_family_stage()
        self._run_spatial_stage()
        self._run_persist_artifacts_stage()
        return self.state.output()

    def _record_stage[ResultT](
        self,
        *,
        stage_name: str,
        prerequisites_met: bool,
        prerequisite_reason: str,
        runner: Callable[[], WholeRunStageExecution[ResultT]],
    ) -> ResultT | None:
        stage_start = time.monotonic()
        if not prerequisites_met:
            self.state.stage_results.append(
                make_stage_result(
                    stage_name=stage_name,
                    status="skipped",
                    stage_start=stage_start,
                    diagnostic_context={"reason": prerequisite_reason},
                )
            )
            return None
        try:
            execution = runner()
        except (aiosqlite.Error, OSError, MemoryError) as exc:
            raise_stage_failure(
                stage_name=stage_name,
                stage_start=stage_start,
                exc=exc,
                diagnostic_context={"run_id": self.context.loaded.run_id},
            )
        self.state.stage_results.append(
            make_stage_result(
                stage_name=stage_name,
                status=execution.status,
                stage_start=stage_start,
                artifacts_created=_artifact_keys(execution.artifact_manifest),
                warnings=execution.warnings,
                diagnostic_context=execution.diagnostic_context,
            )
        )
        return execution.result

    def _run_optional_bundle_stage[BundleT](
        self,
        *,
        stage_name: str,
        prerequisites_met: bool,
        runner: Callable[[], BundleT | None],
    ) -> BundleT | None:
        def execute() -> WholeRunStageExecution[BundleT | None]:
            bundle = runner()
            return _stage_execution(
                bundle,
                artifact_manifest=_bundle_artifact_manifest(bundle),
            )

        return self._record_stage(
            stage_name=stage_name,
            prerequisites_met=prerequisites_met,
            prerequisite_reason="missing_prerequisites",
            runner=execute,
        )

    def _run_spectral_stage(self) -> None:
        loaded = self.context.loaded
        raw_capture_policy = self.context.raw_capture_policy
        self.state.spectral_result = self._record_stage(
            stage_name="BuildWholeRunSpectraStage",
            prerequisites_met=raw_capture_policy.spectra_prerequisites_met(loaded.raw_capture),
            prerequisite_reason=raw_capture_policy.spectra_prerequisite_reason(loaded.raw_capture),
            runner=self._build_spectral_stage,
        )
        if self.state.spectral_result is not None:
            self.state.spectral_bundle = self.state.spectral_result.bundle

    def _build_spectral_stage(
        self,
    ) -> WholeRunStageExecution[WholeRunSpectralBuildResult | None]:
        loaded = self.context.loaded
        raw_capture = loaded.raw_capture
        assert raw_capture is not None
        result = self.context.builders.artifact_builder(
            run_id=loaded.run_id,
            metadata=loaded.metadata,
            raw_capture=raw_capture,
        )
        spectral_manifest = result.bundle.manifest if result.bundle is not None else None
        return _stage_execution(
            result,
            artifact_manifest=spectral_manifest,
            warnings=warning_codes(tuple(result.coverage_summary.warnings)),
            present_diagnostic_context={
                "bundle_available": result.bundle is not None,
                "coverage_confidence": result.coverage_summary.coverage_confidence,
            },
        )

    def _run_context_stage(self) -> None:
        raw_capture_policy = self.context.raw_capture_policy
        self.state.context_bundle = self._record_stage(
            stage_name="BuildWholeRunContextStage",
            prerequisites_met=raw_capture_policy.context_prerequisites_met(),
            prerequisite_reason=raw_capture_policy.context_prerequisite_reason(),
            runner=self._build_context_stage,
        )

    def _build_context_stage(self) -> WholeRunStageExecution[WholeRunContextArtifactBundle | None]:
        raw_capture_manifest = self.context.raw_capture_policy.manifest
        assert raw_capture_manifest is not None
        spectral_result = self.state.spectral_result
        if spectral_result is not None and spectral_result.window_plan is not None:
            bundle = self.context.builders.context_builder(
                run=self.context.run_input,
                window_plan=spectral_result.window_plan,
            )
            return _stage_execution(
                bundle,
                artifact_manifest=_bundle_artifact_manifest(bundle),
                present_diagnostic_context={"build_mode": "window_plan"},
                none_diagnostic_context={"build_mode": "window_plan"},
            )
        bundle = self.context.builders.context_builder(
            run=self.context.run_input,
            total_sample_count=whole_run_total_sample_count(raw_capture_manifest),
        )
        return _stage_execution(
            bundle,
            artifact_manifest=_bundle_artifact_manifest(bundle),
            status_when_present="degraded",
            present_diagnostic_context={"build_mode": "total_sample_count_fallback"},
            none_diagnostic_context={"build_mode": "total_sample_count_fallback"},
        )

    def _run_order_trace_stage(self) -> None:
        self.state.order_trace_bundle = self._run_optional_bundle_stage(
            stage_name="BuildOrderTraceStage",
            prerequisites_met=(
                self.state.spectral_bundle is not None and self.state.context_bundle is not None
            ),
            runner=self._build_order_trace_stage,
        )

    def _build_order_trace_stage(self) -> WholeRunOrderTraceArtifactBundle | None:
        assert self.state.spectral_bundle is not None
        assert self.state.context_bundle is not None
        return self.context.builders.order_trace_builder(
            run=self.context.run_input,
            spectral_bundle=self.state.spectral_bundle,
            context_bundle=self.state.context_bundle,
        )

    def _run_order_trace_summary_stage(self) -> None:
        self.state.order_trace_summary_bundle = self._run_optional_bundle_stage(
            stage_name="BuildOrderTraceSummaryStage",
            prerequisites_met=(
                self.state.order_trace_bundle is not None and self.state.context_bundle is not None
            ),
            runner=self._build_order_trace_summary_stage,
        )

    def _build_order_trace_summary_stage(
        self,
    ) -> WholeRunOrderTraceSummaryArtifactBundle | None:
        assert self.state.order_trace_bundle is not None
        assert self.state.context_bundle is not None
        return self.context.builders.order_trace_summary_builder(
            order_trace_bundle=self.state.order_trace_bundle,
            context_bundle=self.state.context_bundle,
        )

    def _run_order_family_stage(self) -> None:
        self.state.order_family_summary_bundle = self._run_optional_bundle_stage(
            stage_name="BuildOrderFamilySummaryStage",
            prerequisites_met=(
                self.state.order_trace_bundle is not None
                and self.state.order_trace_summary_bundle is not None
                and self.state.context_bundle is not None
            ),
            runner=self._build_order_family_stage,
        )

    def _build_order_family_stage(self) -> WholeRunOrderFamilySummaryArtifactBundle | None:
        assert self.state.order_trace_bundle is not None
        assert self.state.order_trace_summary_bundle is not None
        assert self.state.context_bundle is not None
        return self.context.builders.order_family_summary_builder(
            order_trace_bundle=self.state.order_trace_bundle,
            order_trace_summary_bundle=self.state.order_trace_summary_bundle,
            context_bundle=self.state.context_bundle,
        )

    def _run_spatial_stage(self) -> None:
        self.state.spatial_coherence_bundle = self._run_optional_bundle_stage(
            stage_name="BuildSpatialSummaryStage",
            prerequisites_met=(
                self.state.spectral_bundle is not None
                and self.state.context_bundle is not None
                and self.state.order_trace_bundle is not None
            ),
            runner=self._build_spatial_stage,
        )

    def _build_spatial_stage(self) -> WholeRunSpatialCoherenceArtifactBundle | None:
        assert self.state.spectral_bundle is not None
        assert self.state.context_bundle is not None
        assert self.state.order_trace_bundle is not None
        return self.context.builders.spatial_coherence_builder(
            run=self.context.run_input,
            spectral_bundle=self.state.spectral_bundle,
            context_bundle=self.state.context_bundle,
            order_trace_bundle=self.state.order_trace_bundle,
        )

    def _run_persist_artifacts_stage(self) -> None:
        merged_bundle = merge_whole_run_artifact_bundles(
            self.state.spectral_bundle,
            self.state.context_bundle,
            self.state.order_trace_bundle,
            self.state.order_trace_summary_bundle,
            self.state.order_family_summary_bundle,
            self.state.spatial_coherence_bundle,
        )
        self.state.stored_artifact_manifest = self._record_stage(
            stage_name="PersistArtifactsStage",
            prerequisites_met=merged_bundle is not None,
            prerequisite_reason="no_artifacts_to_persist",
            runner=lambda: self._persist_artifacts_stage(merged_bundle),
        )

    def _persist_artifacts_stage(
        self,
        merged_bundle: StoredWholeRunArtifactBundle | None,
    ) -> WholeRunStageExecution[WholeRunArtifactManifest | None]:
        assert merged_bundle is not None
        stored_manifest = sync_run_persistence_call(
            self.context.db,
            "astore_whole_run_artifacts",
            self.context.loaded.run_id,
            merged_bundle.manifest,
            artifact_contents=merged_bundle.artifact_contents,
        )
        if stored_manifest is None:
            raise OSError(
                f"Failed to persist whole-run artifacts for run {self.context.loaded.run_id}"
            )
        return _stage_execution(
            stored_manifest,
            artifact_manifest=stored_manifest,
            present_diagnostic_context={"artifact_count": len(stored_manifest.artifacts)},
        )
