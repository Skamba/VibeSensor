"""Compose the canonical report document from prepared report input."""

from __future__ import annotations

from vibesensor.report.document.document_context import (
    build_report_document_context,
)
from vibesensor.report.document.document_output import assemble_report_document
from vibesensor.report.document.document_sections import (
    build_report_document_sections,
)
from vibesensor.report.input import PreparedReportInput
from vibesensor.report.model.document import ReportDocument

__all__ = ["compose_report_document"]


def compose_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Compose the canonical report document from prepared report input."""

    context = build_report_document_context(prepared)
    return assemble_report_document(
        context=context,
        sections=build_report_document_sections(context),
    )
