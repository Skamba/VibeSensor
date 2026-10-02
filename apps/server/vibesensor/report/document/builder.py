"""Public facade for composing the PDF-facing report document."""

from __future__ import annotations

from vibesensor.report.document.composition import compose_report_document
from vibesensor.report.input import (
    PreparedReportInput,
    validate_prepared_report_input,
)
from vibesensor.report.model.document import ReportDocument
from vibesensor.report.model.validation import validate_report_document

__all__ = ["build_report_document"]


def build_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Build the final PDF-facing report document from prepared report input."""

    validated_prepared = validate_prepared_report_input(prepared)
    return validate_report_document(compose_report_document(validated_prepared))
