"""Summary payload serialization boundary package.

This package keeps the historical import path stable while splitting the
serialization boundary into focused modules.
"""

from ._findings import annotate_peaks_with_order_labels, serialize_findings
from ._plots import (
    serialize_peak_table,
    serialize_phase_segments,
    serialize_phase_speed_breakdown,
    serialize_plot_data,
    serialize_spectrogram,
    serialize_speed_breakdown,
)
from ._summary import (
    AnalysisSummaryBuildContext,
    build_data_quality_dict,
    build_summary_payload,
    noise_baseline_db,
    serialize_origin_summary,
)

__all__ = [
    "AnalysisSummaryBuildContext",
    "annotate_peaks_with_order_labels",
    "build_data_quality_dict",
    "build_summary_payload",
    "noise_baseline_db",
    "serialize_findings",
    "serialize_origin_summary",
    "serialize_peak_table",
    "serialize_phase_segments",
    "serialize_phase_speed_breakdown",
    "serialize_plot_data",
    "serialize_speed_breakdown",
    "serialize_spectrogram",
]
