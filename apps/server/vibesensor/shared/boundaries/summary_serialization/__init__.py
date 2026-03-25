"""Stable public API for summary payload serialization helpers."""

from ._data_quality import AccelStatisticsLike, build_data_quality_dict
from ._findings import annotate_peaks_with_order_labels, serialize_findings
from ._plots import (
    PhaseSegmentLike,
    PhaseSpeedBreakdownRowLike,
    PlotDataResultLike,
    SpeedBreakdownRowLike,
    serialize_peak_table,
    serialize_phase_segments,
    serialize_phase_speed_breakdown,
    serialize_plot_data,
    serialize_spectrogram,
    serialize_speed_breakdown,
)
from ._summary import build_analysis_summary, noise_baseline_db, serialize_origin_summary

__all__ = [
    "AccelStatisticsLike",
    "annotate_peaks_with_order_labels",
    "build_analysis_summary",
    "build_data_quality_dict",
    "noise_baseline_db",
    "PhaseSegmentLike",
    "PhaseSpeedBreakdownRowLike",
    "PlotDataResultLike",
    "serialize_findings",
    "serialize_origin_summary",
    "serialize_peak_table",
    "serialize_phase_segments",
    "serialize_phase_speed_breakdown",
    "serialize_plot_data",
    "serialize_speed_breakdown",
    "serialize_spectrogram",
    "SpeedBreakdownRowLike",
]
