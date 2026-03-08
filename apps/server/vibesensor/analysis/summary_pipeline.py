"""Compatibility facade for focused run-summary pipeline helpers."""

from __future__ import annotations

from .summary_payload import (
    build_origin_explanation,
    build_sensor_analysis,
    build_summary_payload,
    collect_alternative_locations,
    enrich_with_second_finding,
    summarize_display_location,
    summarize_origin,
    weak_spatial_threshold,
)
from .summary_phases import (
    build_phase_timeline,
    compute_run_timing,
    noise_baseline_db,
    prepare_speed_and_phases,
    serialize_phase_segments,
)
from .summary_suitability import (
    build_data_quality_dict,
    build_run_suitability_checks,
    compute_accel_statistics,
    compute_frame_integrity_counts,
    compute_reference_completeness,
)

__all__ = [
    "build_data_quality_dict",
    "build_origin_explanation",
    "build_phase_timeline",
    "build_run_suitability_checks",
    "build_sensor_analysis",
    "build_summary_payload",
    "collect_alternative_locations",
    "compute_accel_statistics",
    "compute_frame_integrity_counts",
    "compute_reference_completeness",
    "compute_run_timing",
    "enrich_with_second_finding",
    "noise_baseline_db",
    "prepare_speed_and_phases",
    "serialize_phase_segments",
    "summarize_display_location",
    "summarize_origin",
    "weak_spatial_threshold",
]
