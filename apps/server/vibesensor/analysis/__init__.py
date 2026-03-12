"""vibesensor.analysis – post-stop analysis modules.

All analysis logic (findings, ranking, phase segmentation, speed-band
derivation, order-tracking, test-plan generation, strength classification)
lives here.  Report-mapping logic lives in ``vibesensor.report.mapping``.

High-level analysis entry points are re-exported here so callers can use
``from vibesensor.analysis import …`` without depending on file layout.

``FindingPayload`` is the TypedDict shape used for serialised analysis
findings.  ``Finding`` is re-exported as a backward-compatible alias.
"""

from ._types import Finding, FindingPayload, SummaryData, i18n_ref
from .phase_segmentation import DrivingPhase, classify_sample_phase
from .summary_builder import (
    LocalizationAssessment,
    RunAnalysis,
    build_findings_for_samples,
    summarize_log,
    summarize_run_data,
)
from .top_cause_selection import OrderAssessment, confidence_label, select_top_causes

__all__ = [
    "DrivingPhase",
    "Finding",
    "FindingPayload",
    "LocalizationAssessment",
    "OrderAssessment",
    "RunAnalysis",
    "SummaryData",
    "build_findings_for_samples",
    "classify_sample_phase",
    "confidence_label",
    "i18n_ref",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
]
