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
from vibesensor.shared.boundaries.runs.capture import configuration_snapshot_from_run_metadata
from vibesensor.shared.boundaries.runs.projection import (
    car_from_run_metadata,
    symptom_from_run_metadata,
)

from ._analysis_models import FindingsBundle, PreparedAnalysisContext
from ._analysis_result import AnalysisResult
from .metadata_projection import metadata_analysis_settings_items
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
    context: PreparedAnalysisContext,
    findings_bundle: FindingsBundle,
) -> AnalysisResult:
    """Build the final app-level analysis result."""

    metadata = context.context
    summary_speed_stats = _speed_stats(context.prepared.speed_values)
    summary_phase_info = build_phase_summary(context.prepared.phase_segments)
    domain_test_plan = plan_test_actions(findings_bundle.domain_findings)
    plot_data = _plot_data(
        samples=list(context.samples),
        speed_breakdown=context.prepared.speed_breakdown,
        phase_speed_breakdown=context.prepared.phase_speed_breakdown,
        findings=findings_bundle.domain_findings,
        raw_sample_rate_hz=context.prepared.raw_sample_rate_hz,
        steady_speed=context.prepared.is_steady_speed,
        run_noise_baseline_g=context.prepared.run_noise_baseline_g,
        per_sample_phases=context.prepared.per_sample_phases,
        phase_segments=context.prepared.phase_segments,
    )

    test_run = TestRun(
        capture=RunCapture(
            run_id=context.prepared.run_id,
            setup=RunSetup(
                sensors=(
                    Sensor.from_location_codes(context.sensor_locations)
                    if context.sensor_locations
                    else ()
                ),
                speed_source=SpeedSource(),
                configuration_snapshot=configuration_snapshot_from_run_metadata(context.context),
            ),
            analysis_settings=metadata_analysis_settings_items(context.context),
            sample_count=len(context.samples),
            duration_s=context.prepared.duration_s,
        ),
        driving_segments=build_domain_driving_segments(context.prepared.phase_segments),
        findings=findings_bundle.domain_findings,
        top_causes=_final_top_causes(
            findings_bundle.domain_findings,
            findings_bundle.domain_top_causes,
        ),
        speed_profile=context.prepared.speed_profile if context.prepared.speed_values else None,
        suitability=context.run_suitability,
        test_plan=domain_test_plan,
    )
    diagnostic_case = DiagnosticCase.start(
        car=car_from_run_metadata(context.context),
        symptoms=(symptom_from_run_metadata(context.context),),
        test_plan=domain_test_plan,
    ).add_run(test_run)
    return AnalysisResult(
        file_name=context.file_name,
        metadata=metadata,
        samples=context.samples,
        language=context.language,
        include_samples=context.include_samples,
        prepared=context.prepared,
        accel_stats=context.accel_stats,
        reference_complete=context.reference_complete,
        run_suitability=context.run_suitability,
        most_likely_origin=findings_bundle.most_likely_origin,
        phase_timeline=findings_bundle.phase_timeline,
        sensor_locations=context.sensor_locations,
        connected_locations=context.connected_locations,
        sensor_intensity_by_location=context.sensor_intensity_by_location,
        summary_speed_stats=summary_speed_stats,
        summary_phase_info=summary_phase_info,
        plot_data=plot_data,
        test_run=test_run,
        diagnostic_case=diagnostic_case,
    )
