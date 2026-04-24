"""Focused helpers for serializing location-intensity summary rows."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import LocationIntensitySummary
from vibesensor.shared.types.history_analysis_contracts import (
    LocationIntensitySummaryResponse as LocationIntensitySummaryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseIntensityStatsResponse as PhaseIntensityStatsPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    StrengthBucketDistributionResponse as StrengthBucketDistributionPayload,
)


def _location_intensity_summary_payload(
    row: LocationIntensitySummary,
) -> LocationIntensitySummaryPayload:
    bucket_distribution: StrengthBucketDistributionPayload = {
        "total": row.strength_bucket_distribution.total,
        "counts": dict(row.strength_bucket_distribution.counts),
        "percent_time_l0": row.strength_bucket_distribution.percent_time_l0,
        "percent_time_l1": row.strength_bucket_distribution.percent_time_l1,
        "percent_time_l2": row.strength_bucket_distribution.percent_time_l2,
        "percent_time_l3": row.strength_bucket_distribution.percent_time_l3,
        "percent_time_l4": row.strength_bucket_distribution.percent_time_l4,
        "percent_time_l5": row.strength_bucket_distribution.percent_time_l5,
    }
    phase_intensity: dict[str, PhaseIntensityStatsPayload] | None = None
    if row.phase_intensity:
        phase_intensity = {
            phase: {
                "count": stats.count,
                "mean_intensity_db": stats.mean_intensity_db,
                "max_intensity_db": stats.max_intensity_db,
            }
            for phase, stats in row.phase_intensity.items()
        }
    return {
        "location": row.location,
        "partial_coverage": row.partial_coverage,
        "sample_count": row.sample_count,
        "sample_coverage_ratio": row.sample_coverage_ratio,
        "sample_coverage_warning": row.sample_coverage_warning,
        "usable_sample_count": row.usable_sample_count,
        "usable_sample_coverage_ratio": row.usable_sample_coverage_ratio,
        "usable_sample_coverage_warning": row.usable_sample_coverage_warning,
        "mean_intensity_db": row.mean_intensity_db,
        "p50_intensity_db": row.p50_intensity_db,
        "p95_intensity_db": row.p95_intensity_db,
        "max_intensity_db": row.max_intensity_db,
        "dropped_frames_delta": row.dropped_frames_delta,
        "queue_overflow_drops_delta": row.queue_overflow_drops_delta,
        "strength_bucket_distribution": bucket_distribution,
        "phase_intensity": phase_intensity,
    }


def serialize_location_intensity_rows(
    rows: Sequence[LocationIntensitySummary],
) -> list[LocationIntensitySummaryPayload]:
    """Project location-intensity domain rows into summary payload rows."""

    return [_location_intensity_summary_payload(row) for row in rows]
