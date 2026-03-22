"""Analysis-result assembly helpers for diagnostics orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace

from vibesensor.domain import (
    Car,
    ConfigurationSnapshot,
    DiagnosticCase,
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunCapture,
    RunSetup,
    RunSuitability,
    Sensor,
    SpeedSource,
    Symptom,
    TestRun,
)
from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.test_plan import plan_test_actions
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.types.json_types import JsonObject

from ._types import AccelStatistics, PlotDataResultData, Sample
from .plots import _plot_data
from .run_data_preparation import (
    PreparedRunData,
    build_domain_driving_segments,
    build_phase_summary,
)
from .speed_profile_helpers import _speed_stats


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """App-level analysis result for a completed run."""

    file_name: str
    metadata: JsonObject
    samples: tuple[Sample, ...]
    language: str
    include_samples: bool
    prepared: PreparedRunData
    accel_stats: AccelStatistics
    reference_complete: bool
    run_suitability: RunSuitability | None
    most_likely_origin: VibrationOrigin | None
    phase_timeline: tuple[DrivingPhaseInterval, ...]
    sensor_locations: tuple[str, ...]
    connected_locations: frozenset[str]
    sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]
    summary_speed_stats: SpeedProfileSummary
    summary_phase_info: DrivingPhaseSummary
    plot_data: PlotDataResultData

    test_run: TestRun
    diagnostic_case: DiagnosticCase


def _final_top_causes(
    domain_findings: tuple[DomainFinding, ...],
    domain_top_causes: tuple[DomainFinding, ...],
) -> tuple[DomainFinding, ...]:
    top_cause_ids = {finding.finding_id for finding in domain_top_causes if finding.finding_id}
    top_cause_signatures = {
        finding.finding_id: finding.signatures
        for finding in domain_top_causes
        if finding.finding_id and finding.signatures
    }
    result: list[DomainFinding] = []
    for finding in domain_findings:
        if finding.finding_id not in top_cause_ids:
            continue
        signatures = top_cause_signatures.get(finding.finding_id)
        result.append(replace(finding, signatures=signatures) if signatures else finding)
    return tuple(result)


def _scalar_analysis_settings(
    metadata: JsonObject,
) -> tuple[tuple[str, int | float | bool | str], ...]:
    raw_settings = metadata.get("analysis_settings")
    if not isinstance(raw_settings, dict):
        return ()
    return tuple(
        (key, value)
        for key, value in sorted(raw_settings.items())
        if isinstance(value, (int, float, bool, str))
    )


def build_analysis_result(
    *,
    file_name: str,
    metadata: JsonObject,
    samples: list[Sample],
    language: str,
    include_samples: bool,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
    sensor_locations: list[str],
    connected_locations: set[str],
    sensor_intensity_by_location: list[LocationIntensitySummary],
    reference_complete: bool,
    run_suitability: RunSuitability | None,
    most_likely_origin: VibrationOrigin | None,
    phase_timeline: list[DrivingPhaseInterval],
    domain_findings: tuple[DomainFinding, ...],
    domain_top_causes: tuple[DomainFinding, ...],
) -> AnalysisResult:
    """Build the final app-level analysis result."""
    summary_speed_stats = _speed_stats(prepared.speed_values)
    summary_phase_info = build_phase_summary(prepared.phase_segments)
    domain_test_plan = plan_test_actions(domain_findings)
    plot_data = _plot_data(
        samples=samples,
        speed_breakdown=prepared.speed_breakdown,
        phase_speed_breakdown=prepared.phase_speed_breakdown,
        findings=domain_findings,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        steady_speed=prepared.is_steady_speed,
        run_noise_baseline_g=prepared.run_noise_baseline_g,
        per_sample_phases=prepared.per_sample_phases,
        phase_segments=prepared.phase_segments,
    )

    test_run = TestRun(
        capture=RunCapture(
            run_id=prepared.run_id,
            setup=RunSetup(
                sensors=Sensor.from_location_codes(sensor_locations) if sensor_locations else (),
                speed_source=SpeedSource(),
                configuration_snapshot=ConfigurationSnapshot.from_metadata(metadata),
            ),
            analysis_settings=_scalar_analysis_settings(metadata),
            sample_count=len(samples),
            duration_s=prepared.duration_s,
        ),
        driving_segments=build_domain_driving_segments(prepared.phase_segments),
        findings=domain_findings,
        top_causes=_final_top_causes(domain_findings, domain_top_causes),
        speed_profile=prepared.speed_profile if prepared.speed_values else None,
        suitability=run_suitability,
        test_plan=domain_test_plan,
    )
    domain_car = Car.from_metadata(metadata)
    domain_symptoms = (Symptom.from_metadata(metadata),)
    diagnostic_case = DiagnosticCase.start(
        car=domain_car,
        symptoms=domain_symptoms,
        test_plan=domain_test_plan,
    ).add_run(test_run)
    return AnalysisResult(
        file_name=file_name,
        metadata=dict(metadata),
        samples=tuple(samples),
        language=language,
        include_samples=include_samples,
        prepared=prepared,
        accel_stats=accel_stats,
        reference_complete=reference_complete,
        run_suitability=run_suitability,
        most_likely_origin=most_likely_origin,
        phase_timeline=tuple(phase_timeline),
        sensor_locations=tuple(sensor_locations),
        connected_locations=frozenset(connected_locations),
        sensor_intensity_by_location=tuple(sensor_intensity_by_location),
        summary_speed_stats=summary_speed_stats,
        summary_phase_info=summary_phase_info,
        plot_data=plot_data,
        test_run=test_run,
        diagnostic_case=diagnostic_case,
    )
