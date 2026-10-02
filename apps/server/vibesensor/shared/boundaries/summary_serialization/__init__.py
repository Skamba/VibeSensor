"""Stable public API for summary payload serialization helpers."""

from ._data_quality import AccelStatisticsLike, build_data_quality_dict
from ._findings import serialize_findings
from ._plots import (
    PeakTableRowLike,
    PhaseSegmentLike,
    PhaseSpeedBreakdownRowLike,
    SpeedBreakdownRowLike,
    serialize_peak_table,
    serialize_phase_segments,
    serialize_phase_speed_breakdown,
    serialize_speed_breakdown,
)
from ._summary import build_analysis_summary, noise_baseline_db, serialize_origin_summary

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
