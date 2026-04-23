"""Public facade for composing the PDF-facing report document."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting import (
    PreparedReportInput,
    validate_prepared_report_input,
)
from vibesensor.shared.boundaries.reporting.document import (
    ReportDocument,
    validate_report_document,
)

from .composition import compose_report_document

__all__ = ["build_report_document"]


def build_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Build the final PDF-facing report document from prepared report input."""

    validated_prepared = validate_prepared_report_input(prepared)
    return validate_report_document(compose_report_document(validated_prepared))
