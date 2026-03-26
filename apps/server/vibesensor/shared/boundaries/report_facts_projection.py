"""Bridge report-facts warning and suitability data into payload form."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain.run_suitability import RunSuitability
from vibesensor.shared.boundaries.run_suitability import run_suitability_payload
from vibesensor.shared.boundaries.summary_warning import summary_warning_payloads
from vibesensor.shared.run_context_warning import RunContextWarningsInput
from vibesensor.shared.types.history_analysis_contracts import (
    RunSuitabilityCheck,
)
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)
from vibesensor.shared.types.json_types import is_json_array

__all__ = [
    "report_suitability_checks",
    "report_warning_payloads",
]


def report_suitability_checks(
    suitability: RunSuitability | None,
) -> tuple[RunSuitabilityCheck, ...]:
    """Return report-facing suitability checks as an immutable payload tuple."""
    return tuple(run_suitability_payload(suitability))


def report_warning_payloads(
    payload: Mapping[str, object],
    *,
    warnings: RunContextWarningsInput = None,
) -> tuple[SummaryWarningPayload, ...]:
    """Return report-facing warning payloads, preferring explicit warning overrides."""
    if warnings is not None:
        return tuple(summary_warning_payloads(warnings))
    raw_warnings = payload.get("warnings")
    return tuple(summary_warning_payloads(raw_warnings if is_json_array(raw_warnings) else None))
