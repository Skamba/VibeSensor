"""vibesensor.analysis – post-stop analysis modules.

All analysis logic (findings, ranking, phase segmentation, speed-band
derivation, order-tracking, test-plan generation, strength classification)
lives here.  The sibling ``vibesensor.report`` package is renderer-only and
must **not** import from this package.

High-level analysis entry points are re-exported here so callers can use
``from vibesensor.analysis import …`` without depending on file layout.
"""

from ._types import Finding, SummaryData
from .phase_segmentation import DrivingPhase, classify_sample_phase
from .report_mapping_pipeline import map_summary
from .summary_builder import build_findings_for_samples, summarize_log, summarize_run_data
from .top_cause_selection import confidence_label, select_top_causes

__all__ = [
    "DrivingPhase",
    "Finding",
    "SummaryData",
    "build_findings_for_samples",
    "classify_sample_phase",
    "confidence_label",
    "map_summary",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
]
