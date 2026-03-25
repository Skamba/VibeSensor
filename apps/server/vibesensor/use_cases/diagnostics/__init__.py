"""vibesensor.use_cases.diagnostics – post-stop analysis modules.

All analysis logic (findings, ranking, phase segmentation, speed-band
derivation, order-tracking, test-plan generation, strength classification)
lives here.  Report-mapping logic lives in ``vibesensor.adapters.pdf.mapping``.

High-level analysis entry points are re-exported here so callers can use
``from vibesensor.use_cases.diagnostics import …`` without depending on file layout.

``FindingPayload`` and the shared serialized summary contracts
(``AnalysisSummary``, ``AnalysisSummaryCoreResponse``, and
``AnalysisSummaryResponse``) are canonically owned by
``vibesensor.shared.types.history_analysis_contracts``. The boundary serializer
that produces ``AnalysisSummary`` lives in
``vibesensor.shared.boundaries.analysis_summary``, and the domain ``Finding``
lives in ``vibesensor.domain``.
"""

from vibesensor.shared.order_bands import build_order_bands, vehicle_orders_hz
from vibesensor.use_cases.diagnostics._analysis_models import FindingsBuilder
from vibesensor.use_cases.diagnostics._run_loader import _load_run as load_run
from vibesensor.use_cases.diagnostics._types import AnalysisSampleInput
from vibesensor.use_cases.diagnostics.summary_builder import (
    AnalysisResult,
    RunAnalysis,
    build_findings_for_samples,
)

__all__ = [
    "AnalysisResult",
    "AnalysisSampleInput",
    "FindingsBuilder",
    "RunAnalysis",
    "build_findings_for_samples",
    "build_order_bands",
    "load_run",
    "vehicle_orders_hz",
]
