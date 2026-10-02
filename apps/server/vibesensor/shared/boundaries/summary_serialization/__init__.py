"""Stable public API for summary payload serialization helpers."""

from vibesensor.shared.boundaries.summary_serialization._data_quality import (
    AccelStatisticsLike,
    build_data_quality_dict,
)
from vibesensor.shared.boundaries.summary_serialization._findings import serialize_findings
from vibesensor.shared.boundaries.summary_serialization._plots import (
    PeakTableRowLike,
    PhaseSegmentLike,
    PhaseSpeedBreakdownRowLike,
    SpeedBreakdownRowLike,
    serialize_peak_table,
    serialize_phase_segments,
    serialize_phase_speed_breakdown,
    serialize_speed_breakdown,
)
from vibesensor.shared.boundaries.summary_serialization._summary import (
    build_analysis_summary,
    noise_baseline_db,
    serialize_origin_summary,
)

__all__ = [
    "AccelStatisticsLike",
    "build_analysis_summary",
    "build_data_quality_dict",
    "noise_baseline_db",
    "PhaseSegmentLike",
    "PeakTableRowLike",
    "PhaseSpeedBreakdownRowLike",
    "serialize_findings",
    "serialize_origin_summary",
    "serialize_peak_table",
    "serialize_phase_segments",
    "serialize_phase_speed_breakdown",
    "serialize_speed_breakdown",
    "SpeedBreakdownRowLike",
]
