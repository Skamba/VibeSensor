"""Persisted-analysis summary building for completed recording runs."""

from __future__ import annotations

from vibesensor.shared.boundaries.analysis_payloads import analysis_result_to_summary
from vibesensor.shared.boundaries.summary_fields.warnings import summary_warning_payloads
from vibesensor.shared.boundaries.summary_serialization._location_intensity import (
    serialize_location_intensity_rows,
)
from vibesensor.shared.json_utils import payload_object_from_json
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.diagnostics.run_analysis_projection import build_sensor_analysis
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput

_MIN_POST_ANALYSIS_DURATION_S = 1.0


def build_post_analysis_summary(run: PostAnalysisRunInput) -> PersistedAnalysis:
    """Run diagnostics analysis and return the internal persisted-analysis object."""
    from vibesensor.domain import SuitabilityCheck
    from vibesensor.report_i18n import tr
    from vibesensor.use_cases.diagnostics.run_analysis import RunAnalysis

    result = RunAnalysis(
        run.diagnostics_run,
        lang=run.language,
        file_name=run.run_id,
        include_samples=False,
    ).summarize()
    summary_payload = analysis_result_to_summary(result)
    prepared = getattr(result, "prepared", None)
    if prepared is not None and hasattr(prepared, "per_sample_phases"):
        sensor_locations, connected_locations, sensor_intensity = build_sensor_analysis(
            samples=run.samples,
            language=run.language,
            per_sample_phases=list(prepared.per_sample_phases),
        )
        summary_payload["sensor_locations"] = sensor_locations
        summary_payload["sensor_locations_connected_throughout"] = sorted(connected_locations)
        summary_payload["sensor_count_used"] = len(sensor_locations)
        summary_payload["sensor_intensity_by_location"] = serialize_location_intensity_rows(
            sensor_intensity,
        )
    summary_payload["case_id"] = result.diagnostic_case.case_id

    def append_run_suitability_warning(
        *,
        check_key: str,
        state: str,
        explanation: str,
    ) -> None:
        run_suitability = summary_payload.get("run_suitability")
        if run_suitability is None:
            run_suitability = []
            summary_payload["run_suitability"] = run_suitability
        warning_payload: RunSuitabilityCheck = {
            "check_key": check_key,
            "state": state,
            "explanation": explanation,
        }
        run_suitability.append(warning_payload)

    analysis_metadata: JsonObject = {
        "analyzed_sample_count": len(run.samples),
        "total_sample_count": run.total_sample_count,
        "sampling_method": "full" if run.stride == 1 else f"stride_{run.stride}",
        "raw_capture_available": run.raw_replay.raw_capture_available,
        "raw_backed_sample_count": run.raw_replay.raw_backed_sample_count,
        "raw_capture_mode": run.raw_replay.raw_capture_mode,
        "raw_replay_window_count": run.raw_replay.replay_window_count,
        "raw_replay_complete_window_count": run.raw_replay.complete_window_count,
        "raw_replay_partial_window_count": run.raw_replay.partial_window_count,
        "raw_replay_missing_window_count": run.raw_replay.missing_window_count,
        "raw_replay_gap_count": run.raw_replay.gap_count,
        "raw_replay_overlap_count": run.raw_replay.overlap_count,
        "raw_replay_dropped_chunk_count": run.raw_replay.dropped_chunk_count,
        "raw_replay_queue_overflow_chunk_count": run.raw_replay.queue_overflow_chunk_count,
        "raw_replay_invalid_chunk_count": run.raw_replay.invalid_chunk_count,
        "raw_replay_write_error_chunk_count": run.raw_replay.write_error_chunk_count,
        "raw_replay_timing_fallback_count": run.raw_replay.timing_fallback_count,
        "raw_replay_sample_rate_mismatch_count": run.raw_replay.sample_rate_mismatch_count,
        "raw_replay_unanchored_sensor_count": run.raw_replay.unanchored_sensor_count,
        "raw_replay_legacy_sensor_count": run.raw_replay.legacy_sensor_count,
        "raw_replay_sync_unverified_sensor_count": run.raw_replay.sync_unverified_sensor_count,
        "raw_replay_stale_sync_sensor_count": run.raw_replay.stale_sync_sensor_count,
        "raw_replay_high_rtt_sensor_count": run.raw_replay.high_rtt_sensor_count,
        "raw_replay_confidence": run.raw_replay.replay_confidence,
    }
    summary_payload["analysis_metadata"] = payload_object_from_json(analysis_metadata)
    if run.raw_replay.warnings:
        existing_warnings = summary_payload.get("warnings")
        warnings_payload = list(existing_warnings) if isinstance(existing_warnings, list) else []
        warnings_payload.extend(summary_warning_payloads(run.raw_replay.warnings))
        summary_payload["warnings"] = warnings_payload

    sample_rate_hz = _post_analysis_sample_rate_hz(run)
    if sample_rate_hz is not None and run.total_sample_count < max(
        1,
        int(sample_rate_hz * _MIN_POST_ANALYSIS_DURATION_S),
    ):
        short_run_check = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_RUN_DURATION",
            state="warn",
        )
        explanation = tr(run.language, "SUITABILITY_RUN_DURATION_WARNING")
        append_run_suitability_warning(
            check_key=short_run_check.check_key,
            state=short_run_check.state,
            explanation=explanation,
        )

    if run.stride > 1:
        stride_check = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            state="warn",
            details=(("stride", run.stride),),
        )
        explanation = tr(
            run.language,
            "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING",
            stride=str(run.stride),
        )
        append_run_suitability_warning(
            check_key=stride_check.check_key,
            state=stride_check.state,
            explanation=explanation,
        )

    return PersistedAnalysis.from_json_object(summary_payload)


def _post_analysis_sample_rate_hz(run: PostAnalysisRunInput) -> int | None:
    """Resolve the sample rate from the canonical diagnostics context only."""
    raw_sample_rate_hz = run.context.raw_sample_rate_hz
    if raw_sample_rate_hz is not None and raw_sample_rate_hz > 0:
        return int(raw_sample_rate_hz)
    return None
