"""Pure boundary serializer for converting analysis results into AnalysisSummary."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Protocol, cast

from vibesensor.domain import (
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunSuitability,
    TestRun,
)
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.boundaries.finding import step_payloads_from_plan
from vibesensor.shared.boundaries.summary_serialization import (
    AccelStatisticsLike,
    PhaseSegmentLike,
    PhaseSpeedBreakdownRowLike,
    PlotDataResultLike,
    SpeedBreakdownRowLike,
    build_summary_payload,
    serialize_plot_data,
)
from vibesensor.shared.run_context import build_summary_warnings
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import JsonObject


class PreparedRunDataLike(Protocol):
    run_id: str
    duration_s: float
    raw_sample_rate_hz: float | None
    speed_breakdown: Sequence[SpeedBreakdownRowLike]
    phase_speed_breakdown: Sequence[PhaseSpeedBreakdownRowLike]
    phase_segments: Sequence[PhaseSegmentLike]
    run_noise_baseline_g: float | None
    speed_breakdown_skipped_reason: JsonObject | None
    speed_stats_by_phase: Mapping[str, SpeedProfileSummary]
    speed_values: list[float]
    speed_non_null_pct: float


class AnalysisResultLike(Protocol):
    file_name: str
    metadata: JsonObject
    samples: Sequence[JsonObject]
    language: str
    include_samples: bool
    prepared: PreparedRunDataLike
    accel_stats: AccelStatisticsLike
    reference_complete: bool
    run_suitability: RunSuitability | None
    most_likely_origin: VibrationOrigin | None
    phase_timeline: Sequence[DrivingPhaseInterval]
    sensor_locations: Sequence[str]
    connected_locations: Collection[str]
    sensor_intensity_by_location: Sequence[LocationIntensitySummary]
    summary_speed_stats: SpeedProfileSummary
    summary_phase_info: DrivingPhaseSummary
    plot_data: PlotDataResultLike
    test_run: TestRun


def _amp_metric_values(accel_stats: AccelStatisticsLike) -> list[float]:
    raw_values = accel_stats.get("amp_metric_values")
    if not isinstance(raw_values, list):
        return []
    return [float(value) for value in raw_values if isinstance(value, (int, float))]


def analysis_result_to_summary(result: AnalysisResultLike) -> AnalysisSummary:
    """Serialize an app-level diagnostics result at an explicit boundary."""
    summary = build_summary_payload(
        file_name=result.file_name,
        run_id=result.prepared.run_id,
        samples=list(result.samples),
        duration_s=result.prepared.duration_s,
        language=result.language,
        metadata=result.metadata,
        raw_sample_rate_hz=result.prepared.raw_sample_rate_hz,
        speed_breakdown=result.prepared.speed_breakdown,
        phase_speed_breakdown=result.prepared.phase_speed_breakdown,
        phase_segments=result.prepared.phase_segments,
        run_noise_baseline_g=result.prepared.run_noise_baseline_g,
        speed_breakdown_skipped_reason=result.prepared.speed_breakdown_skipped_reason,
        findings=result.test_run.findings,
        top_causes=result.test_run.top_causes,
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
    )
    summary["warnings"] = build_summary_warnings(
        result.metadata,
        reference_complete=result.reference_complete,
    )
    summary["report_date"] = result.metadata.get("end_time_utc") or utc_now_iso()
    summary["plots"] = serialize_plot_data(result.plot_data)
    cast(dict[str, object], summary)["_summary_version"] = 2
    if not result.include_samples:
        summary.pop("samples", None)
    return summary
