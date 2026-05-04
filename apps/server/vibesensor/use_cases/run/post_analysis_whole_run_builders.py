"""Whole-run artifact bundle builders used by the post-analysis executor."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest
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
    WholeRunSpectralArtifactBundle,
    WholeRunSpectralBuildResult,
    build_whole_run_spectral_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import WholeRunWindowPlan
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput


@dataclass(frozen=True, slots=True)
class StoredWholeRunArtifactBundle:
    """Generic sidecar bundle shape for final manifest persistence."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]


def build_whole_run_artifacts(
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


def build_whole_run_context_artifacts(
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


def whole_run_total_sample_count(manifest: RawCaptureManifest) -> int:
    if manifest.sensors:
        return max(int(sensor.sample_count) for sensor in manifest.sensors)
    return max(0, int(manifest.total_samples))


def build_whole_run_order_trace_artifacts(
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


def build_whole_run_order_trace_summary_artifacts(
    *,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle,
    context_bundle: WholeRunContextArtifactBundle,
) -> WholeRunOrderTraceSummaryArtifactBundle | None:
    return build_whole_run_order_trace_summary_artifact_bundle(
        order_trace_bundle=order_trace_bundle,
        context_labels=context_bundle.labels,
    )


def build_whole_run_order_family_summary_artifacts(
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


def build_whole_run_spatial_coherence_artifacts(
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


def merge_whole_run_artifact_bundles(
    *bundles: (
        WholeRunSpectralArtifactBundle
        | WholeRunContextArtifactBundle
        | WholeRunOrderTraceArtifactBundle
        | WholeRunOrderTraceSummaryArtifactBundle
        | WholeRunOrderFamilySummaryArtifactBundle
        | WholeRunSpatialCoherenceArtifactBundle
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
