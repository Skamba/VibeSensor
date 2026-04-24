"""Canonical diagnostics context assembly above the typed sample boundary."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median as _median

from vibesensor.domain import RunSuitability
from vibesensor.shared.types.run_schema import RunMetadata

from ._analysis_models import FindingsBuildRequest, PreparedAnalysisContext
from ._types import AccelStatistics, Sample
from .run_analysis_projection import build_sensor_analysis
from .run_data_preparation import PreparedRunData
from .statistics import _strength_band_key, compute_frame_integrity_counts

__all__ = ["build_findings_request", "prepare_analysis_context"]


def build_findings_request(
    *,
    context: RunMetadata,
    samples: Sequence[Sample],
    language: str,
    prepared: PreparedRunData,
) -> FindingsBuildRequest:
    """Build the findings-specific projection from the canonical typed run context."""

    typed_samples = tuple(samples)
    return FindingsBuildRequest(
        context=context,
        samples=typed_samples,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=prepared.is_steady_speed,
        speed_stddev_kmh=prepared.speed_stddev_kmh,
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
        run_noise_baseline_g=prepared.run_noise_baseline_g,
    )


def prepare_analysis_context(
    *,
    context: RunMetadata,
    samples: Sequence[Sample],
    file_name: str,
    language: str,
    include_samples: bool,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
) -> PreparedAnalysisContext:
    """Assemble the one canonical typed context for diagnostics result building."""

    typed_samples = tuple(samples)
    sensor_locations, connected_locations, sensor_intensity_by_location = build_sensor_analysis(
        samples=typed_samples,
        language=language,
        per_sample_phases=list(prepared.per_sample_phases),
        metadata=context,
    )
    sensor_ids = {client_id for sample in typed_samples if (client_id := sample.client_id)}
    total_dropped, total_overflow = compute_frame_integrity_counts(typed_samples)
    amp_metric_values = accel_stats["amp_metric_values"]
    overall_strength_band_key = (
        _strength_band_key(_median(amp_metric_values)) if amp_metric_values else None
    )
    return PreparedAnalysisContext(
        file_name=file_name,
        context=context,
        samples=typed_samples,
        language=language,
        include_samples=include_samples,
        prepared=prepared,
        accel_stats=accel_stats,
        reference_complete=context.reference_complete,
        overall_strength_band_key=overall_strength_band_key,
        run_suitability=RunSuitability.evaluate(
            steady_speed=prepared.is_steady_speed,
            speed_sufficient=prepared.speed_sufficient,
            sensor_count=len(sensor_ids),
            reference_complete=context.reference_complete,
            sat_count=accel_stats["sat_count"],
            total_dropped=total_dropped,
            total_overflow=total_overflow,
        ),
        sensor_locations=tuple(sensor_locations),
        connected_locations=frozenset(connected_locations),
        sensor_intensity_by_location=tuple(sensor_intensity_by_location),
    )
