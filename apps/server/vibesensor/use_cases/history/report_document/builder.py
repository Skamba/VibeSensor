"""Top-level report-document builder from the canonical assembly stage."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting.contracts import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import ReportDocument

from .assembly import assemble_report_document
from .document_builder import build_report_document_data

__all__ = ["build_report_document"]


def build_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Build the canonical report document from prepared report input."""
    return build_report_document_data(assemble_report_document(prepared))
