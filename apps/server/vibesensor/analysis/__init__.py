"""vibesensor.analysis – post-stop analysis modules.

All analysis logic (findings, ranking, phase segmentation, speed-band
derivation, order-tracking, test-plan generation, strength classification)
lives here.  The sibling ``vibesensor.report`` package is renderer-only and
must **not** import from this package.

Public API re-exported here so that ``from vibesensor.analysis import …``
works the same as importing from the individual sub-modules.

External code (outside this package) must import exclusively through this
module-level API — never from sub-modules directly.
"""

from .phase_segmentation import DrivingPhase, classify_sample_phase
from .report_data_builder import map_summary
from .summary import (
    build_findings_for_samples,
    confidence_label,
    select_top_causes,
    summarize_log,
    summarize_run_data,
)

__all__ = [
    "DrivingPhase",
    "build_findings_for_samples",
    "classify_sample_phase",
    "confidence_label",
    "map_summary",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
]
