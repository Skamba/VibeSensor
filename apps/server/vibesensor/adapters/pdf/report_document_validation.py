"""Validation helpers for the PDF adapter's report-document boundary."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.shared.boundaries.reporting.document import (
    validate_report_document as _validate_report_document,
)

__all__ = ["validate_report_document"]


def validate_report_document(data: ReportDocument) -> ReportDocument:
    """Validate one report document before adapter-side layout planning."""

    return _validate_report_document(data)
