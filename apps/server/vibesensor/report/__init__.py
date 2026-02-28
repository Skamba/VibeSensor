"""vibesensor.report – renderer-only PDF/report modules.

This package contains **only** rendering code.  All analysis logic
(findings, ranking, phase segmentation, strength classification, etc.)
lives in ``vibesensor.analysis``.

For backward compatibility the most-used analysis symbols are
re-exported here so that existing ``from vibesensor.report import …``
call-sites keep working.  New code should import from
``vibesensor.analysis`` directly.
"""

from ..analysis import (
    build_findings_for_samples,
    confidence_label,
    select_top_causes,
    summarize_log,
    summarize_run_data,
)

__all__ = [
    "build_findings_for_samples",
    "confidence_label",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
]
