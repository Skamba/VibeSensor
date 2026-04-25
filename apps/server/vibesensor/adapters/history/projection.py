"""Pure history projection helpers for HTTP and export boundaries."""

from __future__ import annotations

from collections.abc import Mapping
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
from vibesensor.use_cases.history.exports import serialize_run_details_json
from vibesensor.use_cases.history.helpers import strip_internal_fields

__all__ = [
    "build_projected_run_details_json",
    "project_history_insights",
    "project_history_run_record",
]


def _project_persisted_history_analysis(
    analysis: PersistedAnalysis,
    *,
    strip_internal: bool,
) -> JsonObject:
    if has_projectable_report_payload(analysis):
        projected, _ = project_persisted_analysis(analysis)
    else:
        projected = cast(JsonObject, {key: value for key, value in analysis.items()})
    if strip_internal:
        projected = strip_internal_fields(projected)
    return projected


def _project_summary_analysis(analysis: Mapping[str, object]) -> JsonObject:
    if has_projectable_report_payload(analysis):
        projected, _ = project_analysis_summary(cast(JsonObject, dict(analysis)))
    else:
        projected = cast(JsonObject, {key: value for key, value in analysis.items()})
    return strip_internal_fields(projected)


def _project_history_metadata(metadata: Mapping[str, object]) -> JsonObject:
    return run_metadata_to_json_object(run_metadata_from_mapping(metadata))


def project_history_run_record(run: StoredHistoryRun) -> JsonObject:
    """Project persisted analysis fields in a history run for API responses."""
    payload: JsonObject = {
        "run_id": run.run_id,
        "status": run.status.value,
        "sample_count": run.sample_count,
        "metadata": run_metadata_to_json_object(run.metadata),
    }
    if run.error_message is not None:
        payload["error_message"] = run.error_message
    if run.artifact_availability is not None:
        payload["artifact_availability"] = run.artifact_availability.to_json_object()
    if run.raw_capture_finalize is not None:
        payload["raw_capture_finalize"] = run.raw_capture_finalize.to_json_object()
    if run.analysis is not None:
        payload["analysis"] = _project_persisted_history_analysis(
            run.analysis,
            strip_internal=True,
        )
    return payload


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
    payload["metadata"] = run_metadata_to_json_object(run.metadata)
    analysis = run.analysis
    if analysis is None:
        return serialize_run_details_json(
            payload,
            sample_count=sample_count,
            run_id=run_id,
        )
    payload["analysis"] = _project_persisted_history_analysis(
        analysis,
        strip_internal=True,
    )
    return serialize_run_details_json(
        payload,
        sample_count=sample_count,
        run_id=run_id,
    )
