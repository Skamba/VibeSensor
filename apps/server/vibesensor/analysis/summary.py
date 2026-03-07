"""Public summary/selection facade for the diagnosis pipeline."""

from __future__ import annotations

__all__ = [
    "_annotate_peaks_with_order_labels",
    "build_findings_for_samples",
    "confidence_label",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
]

from .summary_builder import (
    annotate_peaks_with_order_labels as _annotate_peaks_with_order_labels,
)
from .summary_builder import build_findings_for_samples, summarize_log, summarize_run_data
from .top_cause_selection import confidence_label, select_top_causes
