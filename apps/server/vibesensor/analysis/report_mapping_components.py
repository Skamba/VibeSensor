"""Compatibility facade for focused summary-to-report component builders."""

from __future__ import annotations

from .report_mapping_actions import (
    build_data_trust_from_summary,
    build_next_steps_from_summary,
)
from .report_mapping_peaks import (
    build_peak_row,
    build_peak_rows_from_plots,
    collect_location_intensity,
    compute_location_hotspot_rows,
    peak_row_system_label,
)
from .report_mapping_systems import (
    build_pattern_evidence,
    build_run_metadata_fields,
    build_system_cards,
    build_version_marker,
    filter_active_sensor_intensity,
    has_relevant_reference_gap,
    humanize_signatures,
    resolve_interpretation,
    resolve_parts_context,
    tire_spec_text,
    top_strength_values,
)

__all__ = [
    "build_data_trust_from_summary",
    "build_next_steps_from_summary",
    "build_pattern_evidence",
    "build_peak_row",
    "build_peak_rows_from_plots",
    "build_run_metadata_fields",
    "build_system_cards",
    "build_version_marker",
    "collect_location_intensity",
    "compute_location_hotspot_rows",
    "filter_active_sensor_intensity",
    "has_relevant_reference_gap",
    "humanize_signatures",
    "peak_row_system_label",
    "resolve_interpretation",
    "resolve_parts_context",
    "tire_spec_text",
    "top_strength_values",
]
