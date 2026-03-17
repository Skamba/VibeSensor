"""vibesensor.use_cases.diagnostics – post-stop analysis modules.

All analysis logic (findings, ranking, phase segmentation, speed-band
derivation, order-tracking, test-plan generation, strength classification)
lives here.  Report-mapping logic lives in ``vibesensor.adapters.pdf.mapping``.

High-level analysis entry points are re-exported here so callers can use
``from vibesensor.use_cases.diagnostics import …`` without depending on file layout.

``FindingPayload`` is the TypedDict shape used for serialised analysis
findings.  The domain ``Finding`` lives in ``vibesensor.domain``.
"""

from vibesensor.use_cases.diagnostics._types import (
    IntensityRow,
    MetadataDict,
    i18n_ref,
)
from vibesensor.use_cases.diagnostics.helpers import PHASE_I18N_KEYS
from vibesensor.use_cases.diagnostics.order_bands import build_order_bands, vehicle_orders_hz
from vibesensor.use_cases.diagnostics.plots import PeakTableRow
from vibesensor.use_cases.diagnostics.strength_labels import (
    certainty_tier,
    strength_label,
    strength_text,
)
from vibesensor.use_cases.diagnostics.summary_builder import (
    AnalysisResult,
    RunAnalysis,
    build_findings_for_samples,
    summarize_log,
    summarize_run_data,
)

__all__ = [
    "AnalysisResult",
    "IntensityRow",
    "MetadataDict",
    "PHASE_I18N_KEYS",
    "PeakTableRow",
    "RunAnalysis",
    "build_findings_for_samples",
    "build_order_bands",
    "certainty_tier",
    "i18n_ref",
    "strength_label",
    "strength_text",
    "summarize_log",
    "summarize_run_data",
    "vehicle_orders_hz",
]
