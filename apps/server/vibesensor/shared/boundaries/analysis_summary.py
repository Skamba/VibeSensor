"""Pure boundary serializer for converting analysis results into AnalysisSummary."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from typing import Protocol

from vibesensor.domain import (
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunSuitability,
    TestRun,
)
from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.summary_serialization import (
    AccelStatisticsLike,
    PhaseSegmentLike,
    PhaseSpeedBreakdownRowLike,
    PlotDataResultLike,
    SpeedBreakdownRowLike,
    build_analysis_summary,
    serialize_plot_data,
)
from vibesensor.shared.boundaries.summary_warning import summary_warning_payloads
from vibesensor.shared.boundaries.test_plan_projection import step_payloads_from_plan
from vibesensor.shared.run_context_warning import (
    RunContextWarningsInput,
    build_summary_warnings,
)
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.json_types import JsonObject


class PreparedRunDataLike(Protocol):
    @property
    def run_id(self) -> str: ...

    @property
    def duration_s(self) -> float: ...

    @property
    def raw_sample_rate_hz(self) -> float | None: ...

    @property
    def speed_breakdown(self) -> Sequence[SpeedBreakdownRowLike]: ...

    @property
    def phase_speed_breakdown(self) -> Sequence[PhaseSpeedBreakdownRowLike]: ...

    @property
    def phase_segments(self) -> Sequence[PhaseSegmentLike]: ...

    @property
    def run_noise_baseline_g(self) -> float | None: ...

    @property
    def speed_breakdown_skipped_reason(self) -> JsonObject | None: ...

    @property
    def speed_stats_by_phase(self) -> Mapping[str, SpeedProfileSummary]: ...

    @property
    def speed_values(self) -> list[float]: ...

    @property
    def speed_non_null_pct(self) -> float: ...


class AnalysisResultLike(Protocol):
    @property
    def file_name(self) -> str: ...

    @property
    def metadata(self) -> JsonObject: ...

    @property
    def samples(self) -> Sequence[JsonObject]: ...

    @property
    def language(self) -> str: ...

    @property
    def include_samples(self) -> bool: ...

    @property
    def prepared(self) -> PreparedRunDataLike: ...

    @property
    def accel_stats(self) -> AccelStatisticsLike: ...

    @property
    def reference_complete(self) -> bool: ...

    @property
    def run_suitability(self) -> RunSuitability | None: ...

    @property
    def most_likely_origin(self) -> VibrationOrigin | None: ...

    @property
    def phase_timeline(self) -> Sequence[DrivingPhaseInterval]: ...

    @property
    def sensor_locations(self) -> Sequence[str]: ...

    @property
    def connected_locations(self) -> Collection[str]: ...

    @property
    def sensor_intensity_by_location(self) -> Sequence[LocationIntensitySummary]: ...

    @property
    def summary_speed_stats(self) -> SpeedProfileSummary: ...

    @property
    def summary_phase_info(self) -> DrivingPhaseSummary: ...

    @property
    def plot_data(self) -> PlotDataResultLike: ...

    @property
    def test_run(self) -> TestRun: ...


def _amp_metric_values(accel_stats: AccelStatisticsLike) -> list[float]:
    raw_values = accel_stats.get("amp_metric_values")
    if not isinstance(raw_values, list):
        return []
    return [float(value) for value in raw_values if isinstance(value, (int, float))]


def _serialized_top_causes(result: AnalysisResultLike) -> tuple[DomainFinding, ...]:
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


def analysis_result_to_summary(result: AnalysisResultLike) -> AnalysisSummary:
    """Serialize an app-level diagnostics result at an explicit boundary."""
    summary = build_analysis_summary(
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
    )
    summary["warnings"] = summary_warning_payloads(
        build_summary_warnings(
            result.metadata,
            reference_complete=result.reference_complete,
        )
    )
    report_date = result.metadata.get("end_time_utc")
    summary["report_date"] = report_date if isinstance(report_date, str) else utc_now_iso()
    summary["plots"] = serialize_plot_data(result.plot_data)
    if not result.include_samples:
        summary.pop("samples", None)
    return summary
