"""Pure history projection helpers for HTTP and export boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from vibesensor.shared.boundaries.analysis_payloads import (
    project_analysis_summary,
    project_persisted_analysis,
)
from vibesensor.shared.boundaries.reporting.summary import has_projectable_report_payload
from vibesensor.shared.boundaries.runs.metadata import (
    run_metadata_from_mapping,
    run_metadata_to_json_object,
)
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.history.exports import serialize_run_details_json
from vibesensor.use_cases.history.helpers import strip_internal_fields

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
    _remove_history_metadata_only_fields(projected)
    return projected


def _project_summary_analysis(analysis: Mapping[str, object]) -> JsonObject:
    projected = _project_analysis_mapping(
        analysis,
        project_projectable=lambda: project_analysis_summary(cast(JsonObject, dict(analysis)))[0],
    )
    projected = strip_internal_fields(projected)
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
    return _apply_projected_run_fields(
        payload,
        metadata=run.metadata,
        analysis=run.analysis,
        strip_internal_analysis=True,
    )


def project_history_insights(analysis: Mapping[str, object]) -> JsonObject:
    """Project persisted insights payloads for HTTP responses."""
    return _project_summary_analysis(analysis)


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
