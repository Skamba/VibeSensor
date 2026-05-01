"""Persisted-analysis summary building for completed recording runs."""

from __future__ import annotations

from collections.abc import Callable
from math import ceil
from typing import TYPE_CHECKING

from vibesensor.shared.boundaries.analysis_payloads import analysis_result_to_summary
from vibesensor.shared.boundaries.summary_fields.warnings import summary_warning_payloads
from vibesensor.shared.boundaries.summary_serialization._location_intensity import (
    serialize_location_intensity_rows,
)
from vibesensor.shared.json_utils import i18n_ref, payload_object_from_json
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_RAW_CAPTURE_FINALIZE_DEGRADED,
    WARNING_CODE_VEHICLE_CONTEXT_ALIGNMENT_INCOMPLETE,
    RunContextWarning,
)
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.json_types import JsonArray, JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.diagnostics.run_analysis_projection import build_sensor_analysis
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput

_MIN_POST_ANALYSIS_DURATION_S = 1.0

if TYPE_CHECKING:
    from vibesensor.domain import SuitabilityCheck


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
            metadata=run.context,
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
        "analyzed_summary_row_count": len(run.samples),
        "total_sample_count": run.total_summary_row_count,
        "total_summary_row_count": run.total_summary_row_count,
        "sampling_method": run.sampling_method,
        "raw_capture_available": run.raw_replay.raw_capture_available,
        "raw_backed_sample_count": run.raw_replay.raw_backed_summary_row_count,
        "raw_backed_summary_row_count": run.raw_replay.raw_backed_summary_row_count,
        "raw_capture_mode": run.raw_replay.raw_capture_mode,
        "raw_replay_window_count": run.raw_replay.replay_window_count,
        "raw_replay_complete_window_count": run.raw_replay.complete_window_count,
        "raw_replay_partial_window_count": run.raw_replay.partial_window_count,
        "raw_replay_missing_window_count": run.raw_replay.missing_window_count,
        "raw_replay_gap_count": run.raw_replay.gap_count,
        "raw_replay_overlap_count": run.raw_replay.overlap_count,
        "raw_replay_dropped_chunk_count": run.raw_replay.dropped_chunk_count,
        "raw_replay_late_packet_chunk_count": run.raw_replay.late_packet_chunk_count,
        "raw_replay_udp_ingest_queue_drop_count": run.raw_replay.udp_ingest_queue_drop_count,
        "raw_replay_queue_overflow_chunk_count": run.raw_replay.queue_overflow_chunk_count,
        "raw_replay_invalid_chunk_count": run.raw_replay.invalid_chunk_count,
        "raw_replay_write_error_chunk_count": run.raw_replay.write_error_chunk_count,
        "raw_capture_loss_policy_severity": run.raw_replay.raw_capture_loss_policy_severity,
        "raw_capture_loss_policy_reason": run.raw_replay.raw_capture_loss_policy_reason,
        "raw_capture_loss_policy_gate_whole_run": (
            run.raw_replay.raw_capture_loss_policy_gate_whole_run
        ),
        "raw_capture_loss_policy_max_sensor_drop_ratio": (
            run.raw_replay.raw_capture_loss_policy_max_sensor_drop_ratio
        ),
        "raw_capture_loss_policy_max_events_per_minute": (
            run.raw_replay.raw_capture_loss_policy_max_events_per_minute
        ),
        "raw_replay_timing_fallback_count": run.raw_replay.timing_fallback_count,
        "raw_replay_sample_rate_mismatch_count": run.raw_replay.sample_rate_mismatch_count,
        "raw_replay_fft_unusable_window_count": run.raw_replay.fft_unusable_window_count,
        "raw_replay_sample_rate_unverified_sensor_count": (
            run.raw_replay.sample_rate_unverified_sensor_count
        ),
        "raw_replay_unanchored_sensor_count": run.raw_replay.unanchored_sensor_count,
        "raw_replay_legacy_sensor_count": run.raw_replay.legacy_sensor_count,
        "raw_replay_sync_unverified_sensor_count": run.raw_replay.sync_unverified_sensor_count,
        "raw_replay_stale_sync_sensor_count": run.raw_replay.stale_sync_sensor_count,
        "raw_replay_high_rtt_sensor_count": run.raw_replay.high_rtt_sensor_count,
        "raw_replay_confidence": run.raw_replay.replay_confidence,
    }
    raw_capture_finalize = run.context.raw_capture_finalize
    if raw_capture_finalize is not None:
        analysis_metadata["raw_capture_finalize_status"] = raw_capture_finalize.status
        if raw_capture_finalize.queue_depth is not None:
            analysis_metadata["raw_capture_finalize_queue_depth"] = raw_capture_finalize.queue_depth
        if raw_capture_finalize.error_summary is not None:
            analysis_metadata["raw_capture_finalize_error_summary"] = (
                raw_capture_finalize.error_summary
            )
    if run.context.strength_algorithm_version is not None:
        analysis_metadata["strength_algorithm_version"] = run.context.strength_algorithm_version
    if run.context.peak_detector_version is not None:
        analysis_metadata["peak_detector_version"] = run.context.peak_detector_version
    if run.context.calibration_profile_id is not None:
        analysis_metadata["calibration_profile_id"] = run.context.calibration_profile_id
    if run.context.vehicle_baseline_profile_id is not None:
        analysis_metadata["vehicle_baseline_profile_id"] = run.context.vehicle_baseline_profile_id
    sensor_mount_profiles: JsonArray = []
    for snapshot in run.context.sensor_snapshots:
        mount_profile: JsonObject = {"sensor_id": snapshot.sensor_id}
        if snapshot.location_code:
            mount_profile["mount_location"] = snapshot.location_code
        if snapshot.mount_orientation is not None:
            mount_profile["mount_orientation"] = snapshot.mount_orientation
        if len(mount_profile) > 1:
            sensor_mount_profiles.append(mount_profile)
    if sensor_mount_profiles:
        analysis_metadata["sensor_mount_profiles"] = sensor_mount_profiles
    if run.summary_duration_s is not None:
        analysis_metadata["summary_duration_s"] = round(run.summary_duration_s, 3)
    if run.raw_min_sensor_sample_count is not None:
        analysis_metadata["raw_min_sensor_sample_count"] = run.raw_min_sensor_sample_count
    if run.raw_min_sensor_duration_s is not None:
        analysis_metadata["raw_min_sensor_duration_s"] = round(run.raw_min_sensor_duration_s, 3)
    unaligned_speed_sample_count = sum(
        1 for sample in run.samples if str(sample.speed_source or "").endswith("_unaligned")
    )
    unaligned_rpm_sample_count = sum(
        1 for sample in run.samples if str(sample.engine_rpm_source or "") == "context_unaligned"
    )
    analysis_metadata["vehicle_context_unaligned_speed_sample_count"] = unaligned_speed_sample_count
    analysis_metadata["vehicle_context_unaligned_rpm_sample_count"] = unaligned_rpm_sample_count
    if run.sampling_method != "full":
        analysis_metadata["sampling_base_stride"] = run.stride
        analysis_metadata["sampling_evenly_spaced_sample_count"] = run.evenly_spaced_sample_count
        analysis_metadata["sampling_event_sample_count"] = run.event_sample_count
        analysis_metadata["sampling_evenly_spaced_row_count"] = run.evenly_spaced_sample_count
        analysis_metadata["sampling_event_row_count"] = run.event_sample_count
    summary_payload["analysis_metadata"] = payload_object_from_json(analysis_metadata)
    summary_warnings: list[RunContextWarning] = list(run.raw_replay.warnings)
    finalize_warning = _raw_capture_finalize_warning(raw_capture_finalize)
    if finalize_warning is not None:
        summary_warnings.append(finalize_warning)
    if unaligned_speed_sample_count > 0 or unaligned_rpm_sample_count > 0:
        summary_warnings.append(
            RunContextWarning(
                code=WARNING_CODE_VEHICLE_CONTEXT_ALIGNMENT_INCOMPLETE,
                severity="warn",
                applies_to="order_analysis",
                title=i18n_ref("RUN_CONTEXT_WARNING_VEHICLE_CONTEXT_ALIGNMENT_TITLE"),
                detail=i18n_ref(
                    "RUN_CONTEXT_WARNING_VEHICLE_CONTEXT_ALIGNMENT_DETAIL",
                    speed_samples=str(max(0, unaligned_speed_sample_count)),
                    rpm_samples=str(max(0, unaligned_rpm_sample_count)),
                ),
            )
        )
    if summary_warnings:
        existing_warnings = summary_payload.get("warnings")
        warnings_payload = list(existing_warnings) if isinstance(existing_warnings, list) else []
        warnings_payload.extend(summary_warning_payloads(summary_warnings))
        summary_payload["warnings"] = warnings_payload

    short_run_check = _short_run_check(run)
    if short_run_check is not None:
        explanation = _translate_check_explanation(
            run.language,
            short_run_check,
            tr=tr,
        )
        append_run_suitability_warning(
            check_key=short_run_check.check_key,
            state=short_run_check.state,
            explanation=explanation,
        )

    if run.sampling_method != "full":
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


def _raw_capture_finalize_warning(
    finalize: object,
) -> RunContextWarning | None:
    from vibesensor.shared.types.run_schema import RunRawCaptureFinalize

    if not isinstance(finalize, RunRawCaptureFinalize) or not finalize.degraded:
        return None
    detail_key = {
        "enqueue_timeout": "RUN_CONTEXT_WARNING_RAW_CAPTURE_FINALIZE_ENQUEUE_TIMEOUT_DETAIL",
        "timeout": "RUN_CONTEXT_WARNING_RAW_CAPTURE_FINALIZE_TIMEOUT_DETAIL",
        "failed": "RUN_CONTEXT_WARNING_RAW_CAPTURE_FINALIZE_FAILED_DETAIL",
    }[finalize.status]
    return RunContextWarning(
        code=WARNING_CODE_RAW_CAPTURE_FINALIZE_DEGRADED,
        severity="warn",
        applies_to="raw_capture",
        title=i18n_ref("RUN_CONTEXT_WARNING_RAW_CAPTURE_FINALIZE_TITLE"),
        detail=i18n_ref(
            detail_key,
            queue_depth=(
                str(max(0, int(finalize.queue_depth)))
                if finalize.queue_depth is not None
                else "unknown"
            ),
            error_summary=finalize.error_summary or "not reported",
        ),
    )


def _post_analysis_sample_rate_hz(run: PostAnalysisRunInput) -> int | None:
    raw_sample_rate_hz = run.context.raw_sample_rate_hz
    if raw_sample_rate_hz is not None and raw_sample_rate_hz > 0:
        return int(raw_sample_rate_hz)
    return None


def _short_run_check(run: PostAnalysisRunInput) -> SuitabilityCheck | None:
    from vibesensor.domain import SuitabilityCheck

    required_raw_samples = _minimum_raw_sample_count(run)
    if run.raw_capture_available and run.raw_min_sensor_duration_s is not None:
        if run.raw_min_sensor_duration_s < _MIN_POST_ANALYSIS_DURATION_S:
            return SuitabilityCheck(
                check_key="SUITABILITY_CHECK_RUN_DURATION",
                state="warn",
                details=(
                    ("raw_samples", max(0, int(run.raw_min_sensor_sample_count or 0))),
                    ("required_raw_samples", max(1, int(required_raw_samples or 0))),
                ),
            )
        return None
    if run.summary_duration_s is not None:
        if run.summary_duration_s < _MIN_POST_ANALYSIS_DURATION_S:
            return SuitabilityCheck(
                check_key="SUITABILITY_CHECK_RUN_DURATION",
                state="warn",
            )
        return None
    required_summary_rows = _minimum_summary_row_count(run)
    if run.total_summary_row_count < required_summary_rows:
        return SuitabilityCheck(
            check_key="SUITABILITY_CHECK_RUN_DURATION",
            state="warn",
            details=(
                ("summary_rows", max(0, int(run.total_summary_row_count))),
                ("required_summary_rows", required_summary_rows),
            ),
        )
    return None


def _minimum_raw_sample_count(run: PostAnalysisRunInput) -> int | None:
    sample_rate_hz = _post_analysis_sample_rate_hz(run)
    if sample_rate_hz is None:
        return None
    return max(1, int(ceil(sample_rate_hz * _MIN_POST_ANALYSIS_DURATION_S)))


def _minimum_summary_row_count(run: PostAnalysisRunInput) -> int:
    feature_interval_s = run.context.feature_interval_s
    if feature_interval_s is not None and feature_interval_s > 0:
        return max(1, int(ceil(_MIN_POST_ANALYSIS_DURATION_S / float(feature_interval_s))))
    return 2


def _translate_check_explanation(
    language: str,
    check: SuitabilityCheck,
    *,
    tr: Callable[..., str],
) -> str:
    explanation = check.explanation_i18n_ref()
    if not isinstance(explanation, dict) or "_i18n_key" not in explanation:
        return str(explanation) if explanation is not None else ""
    key = str(explanation["_i18n_key"])
    params = {k: v for k, v in explanation.items() if k not in {"_i18n_key", "_suffix"}}
    return str(tr(language, key, **params))
