"""Serialize diagnostics results into persisted analysis-summary payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from vibesensor.analysis.diagnosis import build_diagnosis
from vibesensor.common.time_utils import utc_now_iso
from vibesensor.domain.finding import Finding as DomainFinding
from vibesensor.recording.run_metadata import run_metadata_to_json_object
from vibesensor.recording.sensor_frame_mapping import sensor_frames_to_json_objects
from vibesensor.summary.builder import build_analysis_summary
from vibesensor.summary.contracts import AnalysisSummary
from vibesensor.summary.data_quality_payload import AccelStatisticsLike
from vibesensor.summary.plots_payload import serialize_peak_table
from vibesensor.summary.run_context_warning import (
    RunContextWarningsInput,
    build_summary_warnings,
)
from vibesensor.summary.test_plan_fields import step_payloads_from_plan
from vibesensor.summary.warning_fields import summary_warning_payloads

if TYPE_CHECKING:
    from vibesensor.analysis._analysis_result import AnalysisResult

__all__ = ["analysis_result_to_summary", "analysis_summary_with_warnings"]


def _amp_metric_values(accel_stats: AccelStatisticsLike) -> list[float]:
    raw_values = accel_stats.get("amp_metric_values")
    if not isinstance(raw_values, list):
        return []
    return [float(value) for value in raw_values if isinstance(value, (int, float))]


def _serialized_top_causes(result: AnalysisResult) -> tuple[DomainFinding, ...]:
    actionable = tuple(
        finding
        for finding in result.test_run.top_causes
        if not finding.is_reference and finding.is_actionable
    )
    if actionable:
        return actionable
    return tuple(finding for finding in result.test_run.top_causes if not finding.is_reference)


def analysis_summary_with_warnings(
    summary: AnalysisSummary,
    warnings: RunContextWarningsInput,
) -> AnalysisSummary:
    """Return a typed summary copy with report-facing warning payloads replaced."""

    updated_summary = deepcopy(summary)
    updated_summary["warnings"] = summary_warning_payloads(warnings)
    return updated_summary


def analysis_result_to_summary(result: AnalysisResult) -> AnalysisSummary:
    """Serialize an app-level diagnostics result at an explicit boundary."""
    metadata = run_metadata_to_json_object(result.metadata)
    summary = build_analysis_summary(
        file_name=result.file_name,
        run_id=result.prepared.run_id,
        samples=sensor_frames_to_json_objects(result.samples),
        duration_s=result.prepared.duration_s,
        language=result.language,
        metadata=metadata,
        raw_sample_rate_hz=result.prepared.raw_sample_rate_hz,
        speed_breakdown=result.prepared.speed_breakdown,
        phase_speed_breakdown=result.prepared.phase_speed_breakdown,
        phase_segments=result.prepared.phase_segments,
        run_noise_baseline_g=result.prepared.run_noise_baseline_g,
        speed_breakdown_skipped_reason=result.prepared.speed_breakdown_skipped_reason,
        findings=result.test_run.findings,
        top_causes=_serialized_top_causes(result),
        most_likely_origin=result.most_likely_origin,
        test_plan=step_payloads_from_plan(result.test_run.test_plan),
        phase_timeline=list(result.phase_timeline),
        speed_stats=result.summary_speed_stats,
        speed_stats_by_phase=dict(result.prepared.speed_stats_by_phase),
        phase_info=result.summary_phase_info,
        sensor_locations=list(result.sensor_locations),
        connected_locations=set(result.connected_locations),
        sensor_intensity_by_location=list(result.sensor_intensity_by_location),
        run_suitability=result.run_suitability,
        speed_values=result.prepared.speed_values,
        speed_non_null_pct=result.prepared.speed_non_null_pct,
        accel_stats=result.accel_stats,
        amp_metric_values=_amp_metric_values(result.accel_stats),
        diagnosis=build_diagnosis(
            test_run=result.test_run,
            samples=result.samples,
            metadata=result.metadata,
            sensor_count=len(result.sensor_locations),
        ),
    )
    summary["warnings"] = summary_warning_payloads(
        build_summary_warnings(
            metadata,
            reference_complete=result.reference_complete,
        )
    )
    report_date = metadata.get("end_time_utc")
    summary["report_date"] = report_date if isinstance(report_date, str) else utc_now_iso()
    summary["plots"] = {"peaks_table": serialize_peak_table(result.peaks_table)}
    if not result.include_samples:
        summary.pop("samples", None)
    return summary
