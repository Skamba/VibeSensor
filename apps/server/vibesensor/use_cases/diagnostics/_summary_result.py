"""Analysis-result assembly helpers for diagnostics orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

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
from vibesensor.domain.test_plan import plan_test_actions
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.boundaries.finding import step_payloads_from_plan
from vibesensor.shared.boundaries.summary_serialization import (
    build_summary_payload,
    serialize_plot_data,
)
from vibesensor.shared.run_context import build_summary_warnings
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import JsonObject

from ._types import AccelStatistics, Sample
from .plots import _plot_data
from .run_data_preparation import (
    PreparedRunData,
    build_domain_driving_segments,
    build_phase_summary,
)
from .speed_profile_helpers import _speed_stats


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Domain aggregates plus persisted summary payload for a completed run."""

    test_run: TestRun
    diagnostic_case: DiagnosticCase
    summary: AnalysisSummary


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
    """Build the final domain aggregates and persisted summary payload."""
    summary_speed_stats = _speed_stats(prepared.speed_values)
    summary_phase_info = build_phase_summary(prepared.phase_segments)
    domain_test_plan = plan_test_actions(domain_findings)
    summary_test_plan = step_payloads_from_plan(domain_test_plan)

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

    summary = build_summary_payload(
        file_name=file_name,
        run_id=prepared.run_id,
        samples=samples,
        duration_s=prepared.duration_s,
        language=language,
        metadata=metadata,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        speed_breakdown=prepared.speed_breakdown,
        phase_speed_breakdown=prepared.phase_speed_breakdown,
        phase_segments=prepared.phase_segments,
        run_noise_baseline_g=prepared.run_noise_baseline_g,
        speed_breakdown_skipped_reason=prepared.speed_breakdown_skipped_reason,
        findings=domain_findings,
        top_causes=test_run.top_causes,
        most_likely_origin=most_likely_origin,
        test_plan=summary_test_plan,
        phase_timeline=phase_timeline,
        speed_stats=summary_speed_stats,
        speed_stats_by_phase=prepared.speed_stats_by_phase,
        phase_info=summary_phase_info,
        sensor_locations=sensor_locations,
        connected_locations=connected_locations,
        sensor_intensity_by_location=sensor_intensity_by_location,
        run_suitability=run_suitability,
        speed_values=prepared.speed_values,
        speed_non_null_pct=prepared.speed_non_null_pct,
        accel_stats=accel_stats,
        amp_metric_values=accel_stats["amp_metric_values"],
    )
    summary["warnings"] = build_summary_warnings(
        metadata,
        reference_complete=reference_complete,
    )
    summary["report_date"] = metadata.get("end_time_utc") or utc_now_iso()
    summary["plots"] = serialize_plot_data(
        _plot_data(
            samples=samples,
            speed_breakdown=prepared.speed_breakdown,
            phase_speed_breakdown=prepared.phase_speed_breakdown,
            findings=domain_findings,
            raw_sample_rate_hz=prepared.raw_sample_rate_hz,
            steady_speed=prepared.is_steady_speed,
            run_noise_baseline_g=prepared.run_noise_baseline_g,
            per_sample_phases=prepared.per_sample_phases,
            phase_segments=prepared.phase_segments,
        ),
    )
    cast(dict[str, object], summary)["_summary_version"] = 2
    if not include_samples:
        summary.pop("samples", None)
    return AnalysisResult(
        test_run=test_run,
        diagnostic_case=diagnostic_case,
        summary=summary,
    )
