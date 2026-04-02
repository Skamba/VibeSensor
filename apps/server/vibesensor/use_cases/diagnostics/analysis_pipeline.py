"""Pure execution steps for typed diagnostics analysis runs."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import Finding as DomainFinding
from vibesensor.shared.types.run_schema import RunMetadata

from . import _summary_steps
from ._analysis_models import (
    AnalysisResultBuildRequest,
    FindingsBuilder,
    FindingsBuildRequest,
    FindingsBundleRequest,
)
from ._analysis_result import AnalysisResult
from ._analysis_result_builder import build_analysis_result
from ._types import AccelStatistics, Sample
from .findings import _build_findings
from .run_data_preparation import PreparedRunData


def execute_analysis(
    *,
    context: RunMetadata,
    samples: Sequence[Sample],
    file_name: str,
    language: str,
    include_samples: bool,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
    findings_builder: FindingsBuilder | None,
) -> AnalysisResult:
    """Execute the diagnostics pipeline for an already-typed run."""

    reference_complete, run_suitability, overall_strength_band_key = (
        _summary_steps.build_run_suitability_bundle(
            context,
            samples,
            prepared=prepared,
            accel_stats=accel_stats,
        )
    )
    sensor_locations, connected_locations, sensor_intensity_by_location = (
        _summary_steps.build_sensor_bundle(
            samples,
            language=language,
            per_sample_phases=prepared.per_sample_phases,
        )
    )
    findings_request = FindingsBuildRequest(
        context=context,
        samples=samples,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=prepared.is_steady_speed,
        speed_stddev_kmh=prepared.speed_stddev_kmh,
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
        run_noise_baseline_g=prepared.run_noise_baseline_g,
    )
    findings_bundle = _summary_steps.build_findings_bundle(
        FindingsBundleRequest(
            findings_request=findings_request,
            prepared=prepared,
            overall_strength_band_key=overall_strength_band_key,
            has_reference_gaps=not reference_complete,
            sensor_count=len(sensor_locations),
        ),
        findings_builder=findings_builder,
    )
    return build_analysis_result(
        AnalysisResultBuildRequest(
            file_name=file_name,
            context=context,
            samples=samples,
            language=language,
            include_samples=include_samples,
            prepared=prepared,
            accel_stats=accel_stats,
            sensor_locations=sensor_locations,
            connected_locations=connected_locations,
            sensor_intensity_by_location=sensor_intensity_by_location,
            reference_complete=reference_complete,
            run_suitability=run_suitability,
            findings_bundle=findings_bundle,
        ),
    )


def build_findings_for_typed_samples(
    *,
    context: RunMetadata,
    samples: Sequence[Sample],
    language: str,
    prepared: PreparedRunData,
    findings_builder: FindingsBuilder | None = None,
) -> tuple[DomainFinding, ...]:
    """Build findings from canonical typed diagnostics inputs."""

    builder = findings_builder or _build_findings
    return builder(
        FindingsBuildRequest(
            context=context,
            samples=samples,
            speed_sufficient=prepared.speed_sufficient,
            steady_speed=prepared.is_steady_speed,
            speed_stddev_kmh=prepared.speed_stddev_kmh,
            speed_non_null_pct=prepared.speed_non_null_pct,
            raw_sample_rate_hz=prepared.raw_sample_rate_hz,
            lang=language,
            per_sample_phases=prepared.per_sample_phases,
            run_noise_baseline_g=prepared.run_noise_baseline_g,
        ),
    )
