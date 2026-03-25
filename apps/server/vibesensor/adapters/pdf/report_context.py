"""PDF-side bridge helpers for the precomputed report mapping context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vibesensor.adapters.pdf.report_data import PatternEvidence
from vibesensor.use_cases.history.report_preparation import (
    PreparedReportInput,
    ReportMappingContext,
    ValidatedPreparedReportInput,
    validate_prepared_report_input,
)

if TYPE_CHECKING:
    from vibesensor.adapters.pdf._candidate_resolver import PrimaryCandidateContext

__all__ = [
    "ReportMappingContext",
    "observed_signature",
    "prepare_report_mapping_context",
]


def observed_signature(primary: PrimaryCandidateContext) -> PatternEvidence:
    """Build the observed-signature block for the report template."""
    return PatternEvidence(
        primary_system=primary.primary_system,
        strongest_location=primary.primary_location,
        speed_band=primary.primary_speed,
        strength_label=primary.strength_text,
        strength_peak_db=primary.strength_db,
        certainty_label=primary.certainty_label_text,
        certainty_pct=primary.certainty_pct,
        certainty_reason=primary.certainty_reason,
    )


def prepare_report_mapping_context(
    prepared: PreparedReportInput | ValidatedPreparedReportInput,
) -> ReportMappingContext:
    """Return the precomputed report mapping context from the validated handoff."""
    validated = validate_prepared_report_input(prepared)
    return validated.mapping_context
