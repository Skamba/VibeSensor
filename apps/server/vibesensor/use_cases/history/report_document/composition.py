"""Compose the canonical report document from prepared report input."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import ReportDocument

from .document_context import build_report_document_context
from .document_output import assemble_report_document
from .document_sections import build_report_document_sections

__all__ = ["compose_report_document"]


def compose_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Compose the canonical report document from prepared report input."""

    context = build_report_document_context(prepared)
    return assemble_report_document(
        context=context,
        sections=build_report_document_sections(context),
    )
