"""Whole-run summary projection helpers for post-analysis persistence."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import CarOrderReferenceStatus
from vibesensor.shared.boundaries.reporting.fallback_reasons import (
    REPORT_FALLBACK_REASONS_METADATA_KEY,
    derive_report_fallback_reasons,
)
from vibesensor.shared.boundaries.reporting.summary import report_summary_from_mapping
from vibesensor.shared.run_context_warning import (
    RunContextWarningsInput,
    normalize_run_context_warnings,
)
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTraceSummary
from vibesensor.use_cases.diagnostics.orders.whole_run_family_summaries import (
    WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
    WholeRunOrderFamilySummaryArtifactBundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
    WholeRunOrderTraceSummaryArtifactBundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    WholeRunOrderTraceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import SpatialEvidenceSummary
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
    WholeRunContextArtifactBundle,
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
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunSpectralArtifactBundle,
    WholeRunSpectralCoverageSummary,
)


def append_whole_run_analysis_metadata(
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
    analysis_metadata["whole_run_artifacts_status"] = "available"
    analysis_metadata["whole_run_artifact_manifest_path"] = f"{manifest.relative_dir}/manifest.json"
    analysis_metadata["whole_run_artifact_generated_at"] = manifest.created_at
    analysis_metadata["whole_run_artifact_schema_version"] = manifest.schema_version
    analysis_metadata["whole_run_artifact_storage_type"] = manifest.storage_type
    analysis_metadata["whole_run_window_count"] = int(manifest.total_window_count)
    analysis_metadata["whole_run_sensor_count"] = len(sensor_ids)
    analysis_metadata["whole_run_artifact_count"] = len(manifest.artifacts)
    analysis_metadata["whole_run_artifact_keys"] = [
        artifact.artifact_key for artifact in manifest.artifacts
    ]
    analysis_metadata["whole_run_artifact_formats"] = {
        artifact.artifact_key: artifact.file_format for artifact in manifest.artifacts
    }
    analysis_metadata["whole_run_artifact_paths"] = {
        artifact.artifact_key: artifact.relative_path for artifact in manifest.artifacts
    }
    analysis_metadata["whole_run_algorithm_versions"] = dict(manifest.algorithm_versions)
    analysis_metadata["whole_run_artifact_configuration"] = dict(manifest.configuration)
    analysis_metadata["whole_run_source_raw_manifest_count"] = len(manifest.source_raw_manifests)
    analysis_metadata["whole_run_artifact_warnings"] = _warning_codes_from_payload(
        payload.get("warnings")
    )
    return PersistedAnalysis.from_json_object(payload)


def _warning_codes_from_payload(warnings: JsonValue | object) -> list[JsonValue]:
    if not isinstance(warnings, list):
        return []
    codes: list[JsonValue] = []
    for warning in warnings:
        if not is_json_object(warning):
            continue
        code = warning.get("code")
        if isinstance(code, str) and code:
            codes.append(code)
    return codes


def append_whole_run_spectral_metadata(
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


def append_run_context_warnings(
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


def append_whole_run_context(
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


def append_whole_run_order_trace_metadata(
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


def append_whole_run_order_trace_summary_metadata(
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


def append_whole_run_order_family_summary_metadata(
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


def append_whole_run_spatial_coherence_metadata(
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


def append_whole_run_order_summaries(
    summary: PersistedAnalysis,
    bundle: WholeRunOrderFamilySummaryArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    payload["whole_run_order_summaries"] = [
        row.to_json_object() for row in ranked_whole_run_order_summaries(bundle.summaries)
    ]
    return PersistedAnalysis.from_json_object(payload)


def append_whole_run_spatial_summaries(
    summary: PersistedAnalysis,
    bundle: WholeRunSpatialCoherenceArtifactBundle,
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    payload["whole_run_spatial_summaries"] = [
        row.to_json_object() for row in ranked_whole_run_spatial_summaries(bundle.summaries)
    ]
    return PersistedAnalysis.from_json_object(payload)


def append_whole_run_diagnosis_summaries(
    summary: PersistedAnalysis,
    diagnosis_summaries: tuple[WholeRunDiagnosisSummary, ...],
) -> PersistedAnalysis:
    payload = summary.to_json_object()
    payload["whole_run_diagnosis_summaries"] = [row.to_json_object() for row in diagnosis_summaries]
    return PersistedAnalysis.from_json_object(payload)


def append_whole_run_diagnosis_summary_metadata(
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


def refresh_report_fallback_metadata(summary: PersistedAnalysis) -> PersistedAnalysis:
    payload = summary.to_json_object()
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        analysis_metadata = {}
        payload["analysis_metadata"] = analysis_metadata
    normalized = report_summary_from_mapping(payload)
    fallback_reasons = derive_report_fallback_reasons(
        analysis_metadata,
        has_whole_run_context_intervals=bool(normalized.whole_run_context_intervals),
        has_whole_run_order_summaries=bool(normalized.whole_run_order_summaries),
        has_whole_run_spatial_summaries=bool(normalized.whole_run_spatial_summaries),
        has_whole_run_diagnosis_summaries=bool(normalized.whole_run_diagnosis_summaries),
    )
    if fallback_reasons:
        analysis_metadata[REPORT_FALLBACK_REASONS_METADATA_KEY] = list(fallback_reasons)
    else:
        analysis_metadata.pop(REPORT_FALLBACK_REASONS_METADATA_KEY, None)
    return PersistedAnalysis.from_json_object(payload)


def build_diagnosis_summary_rows(
    *,
    analysis_metadata: Mapping[str, object],
    context_bundle: WholeRunContextArtifactBundle,
    order_summaries: tuple[OrderTraceSummary, ...],
    spatial_summaries: tuple[SpatialEvidenceSummary, ...],
    car_order_reference_status: CarOrderReferenceStatus | None,
) -> tuple[WholeRunDiagnosisSummary, ...]:
    return build_whole_run_diagnosis_summaries(
        analysis_metadata=analysis_metadata,
        context_intervals=context_bundle.intervals,
        order_summaries=order_summaries,
        spatial_summaries=spatial_summaries,
        car_order_reference_status=car_order_reference_status,
    )


def ranked_whole_run_order_summaries(
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


def ranked_whole_run_spatial_summaries(
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
