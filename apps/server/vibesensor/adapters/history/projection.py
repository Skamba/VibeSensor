"""Pure history projection helpers for HTTP and export boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from vibesensor.shared.boundaries.analysis_summary_projection import project_persisted_analysis
from vibesensor.shared.boundaries.report_payload_gate import has_projectable_report_payload
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_to_json_object
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.exports import serialize_run_details_json
from vibesensor.use_cases.history.helpers import strip_internal_fields
from vibesensor.use_cases.run.run_context import run_context_snapshot_from_metadata

__all__ = [
    "build_projected_run_details_json",
    "project_history_insights",
    "project_history_run_record",
]


def _project_history_analysis(
    analysis: PersistedAnalysis | Mapping[str, object],
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


def _project_history_metadata(metadata: Mapping[str, object]) -> JsonObject:
    projected = cast(JsonObject, {key: value for key, value in metadata.items()})
    context_snapshot = run_context_snapshot_from_metadata(projected)
    order_reference_spec = context_snapshot.order_reference_spec
    if order_reference_spec is not None and order_reference_spec.supports_wheel_reference:
        projected["tire_circumference_m"] = order_reference_spec.tire_circumference_m
    return projected


def project_history_run_record(run: StoredHistoryRun) -> JsonObject:
    """Project persisted analysis fields in a history run for API responses."""
    payload: JsonObject = {
        "run_id": run.run_id,
        "status": run.status.value,
        "sample_count": run.sample_count,
        "metadata": _project_history_metadata(run_metadata_to_json_object(run.metadata)),
    }
    if run.error_message is not None:
        payload["error_message"] = run.error_message
    if run.analysis is not None:
        payload["analysis"] = _project_history_analysis(
            run.analysis,
            strip_internal=True,
        )
    return payload


def project_history_insights(analysis: Mapping[str, object]) -> JsonObject:
    """Project persisted insights payloads for HTTP responses."""
    return _project_history_analysis(analysis, strip_internal=True)


def build_projected_run_details_json(
    run: StoredHistoryRun,
    sample_count: int,
    run_id: str,
) -> str:
    """Build the exported JSON metadata document with canonical projected analysis."""
    payload = run.to_json_object()
    payload["metadata"] = _project_history_metadata(run_metadata_to_json_object(run.metadata))
    analysis = run.analysis
    if analysis is None:
        return serialize_run_details_json(
            payload,
            sample_count=sample_count,
            run_id=run_id,
        )
    payload["analysis"] = _project_history_analysis(
        analysis,
        strip_internal=True,
    )
    return serialize_run_details_json(
        payload,
        sample_count=sample_count,
        run_id=run_id,
    )
