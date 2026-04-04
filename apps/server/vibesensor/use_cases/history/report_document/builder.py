"""Public facade for composing the PDF-facing report document."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import ReportDocument

from .composition import compose_report_document

__all__ = ["build_report_document"]


def build_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Build the final PDF-facing report document from prepared report input."""

    return compose_report_document(prepared)
