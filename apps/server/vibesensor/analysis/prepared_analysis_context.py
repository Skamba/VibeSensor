"""Canonical diagnostics context assembly above the typed sample boundary."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.analysis._analysis_models import (
    PreparedAnalysisContext,
)
from vibesensor.analysis._types import AccelStatistics, Sample
from vibesensor.analysis.mount_tilt import find_loose_mounts
from vibesensor.analysis.run_analysis_projection import build_sensor_analysis
from vibesensor.analysis.run_data_preparation import PreparedRunData
from vibesensor.analysis.speed_profile_helpers import run_speed_source, speed_typed_in
from vibesensor.analysis.statistics import compute_frame_integrity_counts
from vibesensor.domain.run_suitability import RunSuitability
from vibesensor.recording.run_schema import RunMetadata

__all__ = ["prepare_analysis_context"]


def prepare_analysis_context(
    *,
    context: RunMetadata,
    samples: Sequence[Sample],
    file_name: str,
    language: str,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
    window_means: Sequence[tuple[float, float, float] | None] = (),
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
    loose_mounts = find_loose_mounts(typed_samples, window_means, metadata=context)
    return PreparedAnalysisContext(
        file_name=file_name,
        context=context,
        samples=typed_samples,
        language=language,
        prepared=prepared,
        accel_stats=accel_stats,
        reference_complete=context.reference_complete,
        run_suitability=RunSuitability.evaluate(
            steady_speed=prepared.is_steady_speed,
            speed_sufficient=prepared.speed_sufficient,
            manual_speed=speed_typed_in(run_speed_source(samples)),
            sensor_count=len(sensor_ids),
            reference_complete=context.reference_complete,
            sat_count=accel_stats["sat_count"],
            total_dropped=total_dropped,
            total_overflow=total_overflow,
        ).with_loose_mounts(len(loose_mounts)),
        sensor_locations=tuple(sensor_locations),
        connected_locations=frozenset(connected_locations),
        sensor_intensity_by_location=tuple(sensor_intensity_by_location),
        loose_mounts=loose_mounts,
    )
