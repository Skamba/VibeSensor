"""Analysis-result assembly helpers for diagnostics orchestration."""

from __future__ import annotations

from vibesensor.domain import (
    DiagnosticCase,
    RunCapture,
    RunSetup,
    Sensor,
    SpeedSource,
    TestRun,
)
from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.test_plan import plan_test_actions

from ._analysis_models import AnalysisResultBuildRequest
from ._analysis_result import AnalysisResult
from .context_codec import (
    diagnostics_analysis_settings_items,
    diagnostics_car,
    diagnostics_configuration_snapshot,
    diagnostics_context_to_run_metadata,
    diagnostics_symptom,
)
from .plots import _plot_data
from .run_analysis_projection import build_domain_driving_segments
from .run_data_preparation import build_phase_summary
from .speed_profile_helpers import _speed_stats

__all__ = ["AnalysisResult", "build_analysis_result", "_final_top_causes"]


def _final_top_causes(
    domain_findings: tuple[DomainFinding, ...],
    domain_top_causes: tuple[DomainFinding, ...],
) -> tuple[DomainFinding, ...]:
    if not domain_top_causes:
        return ()
    top_causes_by_id = {
        finding.finding_id: finding for finding in domain_top_causes if finding.finding_id
    }
    if top_causes_by_id:
        return tuple(
            top_causes_by_id[finding.finding_id]
            for finding in domain_findings
            if finding.finding_id in top_causes_by_id
        )
    domain_findings_set = set(domain_findings)
    return tuple(finding for finding in domain_top_causes if finding in domain_findings_set)


def build_analysis_result(
    request: AnalysisResultBuildRequest,
) -> AnalysisResult:
    """Build the final app-level analysis result."""

    metadata = diagnostics_context_to_run_metadata(request.context)
    findings_bundle = request.findings_bundle
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
                configuration_snapshot=diagnostics_configuration_snapshot(request.context),
            ),
            analysis_settings=diagnostics_analysis_settings_items(request.context),
            sample_count=len(request.samples),
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
    diagnostic_case = DiagnosticCase.start(
        car=diagnostics_car(request.context),
        symptoms=(diagnostics_symptom(request.context),),
        test_plan=domain_test_plan,
    ).add_run(test_run)
    return AnalysisResult(
        file_name=request.file_name,
        metadata=metadata,
        samples=tuple(request.samples),
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
