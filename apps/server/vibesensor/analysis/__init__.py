"""vibesensor.analysis – post-stop analysis modules.

All analysis logic (findings, ranking, phase segmentation, speed-band
derivation, order-tracking, test-plan generation, strength classification)
lives here.  Report-mapping logic lives in ``vibesensor.report.mapping``.

High-level analysis entry points are re-exported here so callers can use
``from vibesensor.analysis import …`` without depending on file layout.

``FindingPayload`` is the TypedDict shape used for serialised analysis
findings.  The domain ``Finding`` lives in ``vibesensor.domain``.
"""

from ..domain import DrivingPhase
from ._types import AnalysisSummary, FindingPayload, i18n_ref
from .order_bands import build_order_bands, vehicle_orders_hz
from .phase_segmentation import classify_sample_phase
from .summary_builder import (
    LocalizationAssessment,
    RunAnalysis,
    build_findings_for_samples,
    summarize_log,
    summarize_run_data,
)
from .top_cause_selection import confidence_label, select_top_causes

__all__ = [
    "DrivingPhase",
    "FindingPayload",
    "LocalizationAssessment",
    "RunAnalysis",
    "AnalysisSummary",
    "build_findings_for_samples",
    "build_order_bands",
    "classify_sample_phase",
    "confidence_label",
    "i18n_ref",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
    "vehicle_orders_hz",
]
