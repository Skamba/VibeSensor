"""vibesensor.use_cases.diagnostics – post-stop analysis modules.

All analysis logic (findings, ranking, phase segmentation, speed-band
derivation, order-tracking, test-plan generation, strength classification)
lives here.  Report-mapping logic lives in ``vibesensor.adapters.pdf.mapping``.

High-level analysis entry points are re-exported here so callers can use
``from vibesensor.use_cases.diagnostics import …`` without depending on file layout.

``FindingPayload`` is the TypedDict shape used for serialised analysis
findings.  The domain ``Finding`` lives in ``vibesensor.domain``.
"""

from vibesensor.shared.order_bands import build_order_bands, vehicle_orders_hz
from vibesensor.use_cases.diagnostics.summary_builder import (
    AnalysisResult,
    RunAnalysis,
    build_findings_for_samples,
)

__all__ = [
    "AnalysisResult",
    "RunAnalysis",
    "build_findings_for_samples",
    "build_order_bands",
    "vehicle_orders_hz",
]
