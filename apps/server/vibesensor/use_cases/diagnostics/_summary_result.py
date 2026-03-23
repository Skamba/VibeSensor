"""Analysis-result assembly helpers for diagnostics orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace

from vibesensor.domain import (
    DiagnosticCase,
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunCapture,
    RunSetup,
    RunSuitability,
    Sensor,
    SpeedSource,
    TestRun,
)
from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.test_plan import plan_test_actions
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.types.json_types import JsonObject

from ._analysis_models import AnalysisResultBuildRequest
from ._context_projection import (
    context_to_car,
    context_to_configuration_snapshot,
    context_to_metadata_dict,
    context_to_symptom,
)
from ._types import AccelStatistics, PlotDataResultData
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
    samples: tuple[JsonObject, ...]
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


def build_analysis_result(
    request: AnalysisResultBuildRequest,
) -> AnalysisResult:
    """Build the final app-level analysis result."""
    findings_bundle = request.findings_bundle
    context_metadata = context_to_metadata_dict(request.context)
    summary_speed_stats = _speed_stats(request.prepared.speed_values)
    summary_phase_info = build_phase_summary(request.prepared.phase_segments)
    domain_test_plan = plan_test_actions(findings_bundle.domain_findings)
    plot_data = _plot_data(
        samples=list(request.samples),
        speed_breakdown=request.prepared.speed_breakdown,
        phase_speed_breakdown=request.prepared.phase_speed_breakdown,
        findings=findings_bundle.domain_findings,
        raw_sample_rate_hz=request.prepared.raw_sample_rate_hz,
        steady_speed=request.prepared.is_steady_speed,
        run_noise_baseline_g=request.prepared.run_noise_baseline_g,
        per_sample_phases=request.prepared.per_sample_phases,
        phase_segments=request.prepared.phase_segments,
    )

    test_run = TestRun(
        capture=RunCapture(
            run_id=request.prepared.run_id,
            setup=RunSetup(
                sensors=(
                    Sensor.from_location_codes(request.sensor_locations)
                    if request.sensor_locations
                    else ()
                ),
                speed_source=SpeedSource(),
                configuration_snapshot=context_to_configuration_snapshot(request.context),
            ),
            analysis_settings=request.context.scalar_analysis_settings,
            sample_count=len(request.raw_samples),
            duration_s=request.prepared.duration_s,
        ),
        driving_segments=build_domain_driving_segments(request.prepared.phase_segments),
        findings=findings_bundle.domain_findings,
        top_causes=_final_top_causes(
            findings_bundle.domain_findings,
            findings_bundle.domain_top_causes,
        ),
        speed_profile=request.prepared.speed_profile if request.prepared.speed_values else None,
        suitability=request.run_suitability,
        test_plan=domain_test_plan,
    )
    domain_car = context_to_car(request.context)
    domain_symptoms = (context_to_symptom(request.context),)
    diagnostic_case = DiagnosticCase.start(
        car=domain_car,
        symptoms=domain_symptoms,
        test_plan=domain_test_plan,
    ).add_run(test_run)
    return AnalysisResult(
        file_name=request.file_name,
        metadata=context_metadata,
        samples=tuple(request.raw_samples),
        language=request.language,
        include_samples=request.include_samples,
        prepared=request.prepared,
        accel_stats=request.accel_stats,
        reference_complete=request.reference_complete,
        run_suitability=request.run_suitability,
        most_likely_origin=findings_bundle.most_likely_origin,
        phase_timeline=findings_bundle.phase_timeline,
        sensor_locations=tuple(request.sensor_locations),
        connected_locations=frozenset(request.connected_locations),
        sensor_intensity_by_location=tuple(request.sensor_intensity_by_location),
        summary_speed_stats=summary_speed_stats,
        summary_phase_info=summary_phase_info,
        plot_data=plot_data,
        test_run=test_run,
        diagnostic_case=diagnostic_case,
    )
