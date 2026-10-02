"""Pure history projection helpers for HTTP and export boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from vibesensor.common.json_types import JsonObject
from vibesensor.domain.run_status import RunStatus
from vibesensor.domain.test_run import TestRun
from vibesensor.history.exports import serialize_run_details_json
from vibesensor.history.helpers import strip_internal_fields
from vibesensor.history.records import StoredHistoryRun
from vibesensor.recording.raw_capture_quality import assess_raw_capture_loss_policy
from vibesensor.recording.run_metadata import (
    run_metadata_from_mapping,
    run_metadata_to_json_object,
)
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.run_suitability_codec import run_suitability_payload
from vibesensor.summary.analysis_metadata import (
    report_analysis_metadata_from_mapping,
)
from vibesensor.summary.decoding import (
    has_projectable_report_payload,
    report_summary_from_mapping,
)
from vibesensor.summary.fallback_reasons import (
    REPORT_FALLBACK_REASONS_METADATA_KEY,
    dedupe_report_fallback_reasons,
    derive_report_fallback_reasons,
    finalization_stage_fallback_reasons,
)
from vibesensor.summary.finding_fields import finding_payload_from_domain
from vibesensor.summary.origin_fields import origin_payload_from_finding
from vibesensor.summary.persisted_analysis import PersistedAnalysis
from vibesensor.summary.reconstruction import (
    test_run_from_persisted_analysis,
    test_run_from_summary,
)
from vibesensor.summary.test_plan_fields import (
    _has_structured_step_content,
    step_payloads_from_plan,
)

__all__ = [
    "build_projected_run_details_json",
    "project_history_insights",
    "project_history_run_record",
]


def _project_analysis_mapping(
    analysis: Mapping[str, object],
    *,
    project_projectable: Callable[[], JsonObject],
) -> JsonObject:
    if has_projectable_report_payload(analysis):
        return project_projectable()
    return cast(JsonObject, {key: value for key, value in analysis.items()})


def _project_persisted_history_analysis(
    analysis: PersistedAnalysis,
    *,
    strip_internal: bool,
) -> JsonObject:
    projected = _project_analysis_mapping(
        analysis,
        project_projectable=lambda: project_persisted_analysis(analysis)[0],
    )
    if strip_internal:
        projected = strip_internal_fields(projected)
    _apply_projected_analysis_fallback_reasons(projected)
    _remove_history_metadata_only_fields(projected)
    return projected


def _project_summary_analysis(analysis: Mapping[str, object]) -> JsonObject:
    projected = _project_analysis_mapping(
        analysis,
        project_projectable=lambda: project_analysis_summary(cast(JsonObject, dict(analysis)))[0],
    )
    projected = strip_internal_fields(projected)
    _apply_projected_analysis_fallback_reasons(projected)
    _remove_history_metadata_only_fields(projected)
    return projected


def _remove_history_metadata_only_fields(payload: JsonObject) -> None:
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("finalization_stages", None)


def _project_history_metadata(metadata: Mapping[str, object] | RunMetadata) -> JsonObject:
    if isinstance(metadata, RunMetadata):
        return run_metadata_to_json_object(metadata)
    return run_metadata_to_json_object(run_metadata_from_mapping(metadata))


def _apply_projected_run_fields(
    payload: JsonObject,
    *,
    metadata: Mapping[str, object] | RunMetadata,
    analysis: PersistedAnalysis | None,
    strip_internal_analysis: bool,
) -> JsonObject:
    metadata_payload = _project_history_metadata(metadata)
    if (finalization_stages := metadata_payload.pop("finalization_stages", None)) is not None:
        payload["finalization_stages"] = finalization_stages
    payload["metadata"] = metadata_payload
    if analysis is not None:
        payload["analysis"] = _project_persisted_history_analysis(
            analysis,
            strip_internal=strip_internal_analysis,
        )
    return payload


def project_history_run_record(run: StoredHistoryRun) -> JsonObject:
    """Project persisted analysis fields in a history run for API responses."""
    payload: JsonObject = {
        "run_id": run.run_id,
        "status": run.status.value,
        "sample_count": run.sample_count,
    }
    if run.error_message is not None:
        payload["error_message"] = run.error_message
    if run.lifecycle is not None:
        payload["lifecycle"] = run.lifecycle.to_json_object()
    if run.artifact_availability is not None:
        payload["artifact_availability"] = run.artifact_availability.to_json_object()
    if run.raw_capture_finalize is not None:
        payload["raw_capture_finalize"] = run.raw_capture_finalize.to_json_object()
    if run.raw_capture_manifest is not None:
        payload["raw_capture_quality"] = assess_raw_capture_loss_policy(
            run.raw_capture_manifest
        ).to_json_object()
    if fallback_reasons := _history_run_fallback_reasons(run):
        payload["fallback_reasons"] = list(fallback_reasons)
    return _apply_projected_run_fields(
        payload,
        metadata=run.metadata,
        analysis=run.analysis,
        strip_internal_analysis=True,
    )


def project_history_insights(analysis: Mapping[str, object]) -> JsonObject:
    """Project persisted insights payloads for HTTP responses."""
    return _project_summary_analysis(analysis)


def _apply_projected_analysis_fallback_reasons(payload: JsonObject) -> None:
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, dict):
        return
    normalized = report_summary_from_mapping(payload)
    reasons = derive_report_fallback_reasons(
        report_analysis_metadata_from_mapping(analysis_metadata),
        has_whole_run_context_intervals=bool(normalized.whole_run_context_intervals),
        has_whole_run_order_summaries=bool(normalized.whole_run_order_summaries),
        has_whole_run_spatial_summaries=bool(normalized.whole_run_spatial_summaries),
        has_whole_run_diagnosis_summaries=bool(normalized.whole_run_diagnosis_summaries),
    )
    if reasons:
        analysis_metadata[REPORT_FALLBACK_REASONS_METADATA_KEY] = list(reasons)
    else:
        analysis_metadata.pop(REPORT_FALLBACK_REASONS_METADATA_KEY, None)


def _history_run_fallback_reasons(run: StoredHistoryRun) -> tuple[str, ...]:
    reasons: list[str] = []
    reasons.extend(finalization_stage_fallback_reasons(run.metadata.finalization_stages))
    if run.analysis is None:
        if run.lifecycle is not None and run.lifecycle.post_analysis in {"pending", "running"}:
            reasons.append("whole_run_analysis_pending")
        elif run.status in {RunStatus.RECORDING, RunStatus.ANALYZING}:
            reasons.append("whole_run_analysis_pending")
        elif run.status == RunStatus.ERROR or run.error_message:
            reasons.append("whole_run_analysis_failed")
        elif run.lifecycle is not None and run.lifecycle.post_analysis == "degraded":
            reasons.append("whole_run_analysis_failed")
    else:
        payload = run.analysis.to_json_object()
        analysis_metadata = payload.get("analysis_metadata")
        if isinstance(analysis_metadata, dict):
            normalized = report_summary_from_mapping(payload)
            reasons.extend(
                derive_report_fallback_reasons(
                    report_analysis_metadata_from_mapping(analysis_metadata),
                    has_whole_run_context_intervals=bool(normalized.whole_run_context_intervals),
                    has_whole_run_order_summaries=bool(normalized.whole_run_order_summaries),
                    has_whole_run_spatial_summaries=bool(normalized.whole_run_spatial_summaries),
                    has_whole_run_diagnosis_summaries=bool(
                        normalized.whole_run_diagnosis_summaries
                    ),
                )
            )
    return tuple(dedupe_report_fallback_reasons(reasons))


def build_projected_run_details_json(
    run: StoredHistoryRun,
    sample_count: int,
    run_id: str,
) -> str:
    """Build the exported JSON metadata document with canonical projected analysis."""
    payload = run.to_json_object()
    payload = _apply_projected_run_fields(
        payload,
        metadata=run.metadata,
        analysis=run.analysis,
        strip_internal_analysis=True,
    )
    return serialize_run_details_json(
        payload,
        sample_count=sample_count,
        run_id=run_id,
    )


def _project_analysis_payload(
    analysis: Mapping[str, object],
    *,
    test_run: TestRun,
) -> JsonObject:
    projected: dict[str, object] = dict(analysis)
    projected["findings"] = [finding_payload_from_domain(f) for f in test_run.findings]
    projected["top_causes"] = [
        finding_payload_from_domain(f) for f in test_run.effective_top_causes()
    ]
    primary = test_run.primary_finding
    projected["most_likely_origin"] = (
        origin_payload_from_finding(primary) if primary is not None else {}
    )
    if not _has_structured_step_content(analysis.get("test_plan")):
        projected["test_plan"] = step_payloads_from_plan(test_run.test_plan)
    projected["run_suitability"] = run_suitability_payload(test_run.suitability)
    return cast(JsonObject, projected)


def project_analysis_summary(analysis: JsonObject) -> tuple[JsonObject, TestRun]:
    """Reconstruct and re-serialize an outward analysis summary."""
    test_run = test_run_from_summary(analysis)
    return _project_analysis_payload(analysis, test_run=test_run), test_run


def project_persisted_analysis(
    analysis: PersistedAnalysis,
) -> tuple[JsonObject, TestRun]:
    """Reconstruct and re-serialize storage-owned persisted analysis."""
    payload = analysis.to_json_object()
    test_run = test_run_from_persisted_analysis(analysis)
    return _project_analysis_payload(payload, test_run=test_run), test_run
