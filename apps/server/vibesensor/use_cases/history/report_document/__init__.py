"""Canonical report-document assembly above the PDF renderer boundary."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting import (
    PreparedReportInput,
    prepare_persisted_report_input,
    prepare_report_input,
)
from vibesensor.shared.boundaries.reporting.document import (
    Report,
    ReportDocument,
    ReportDocumentContext,
)

from ._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from ._card_builder import build_system_cards, humanize_signatures
from .builder import ReportDocumentBuilder, build_report_document, build_report_document_data
from .composition import compose_report_document_context

__all__ = [
    "PreparedReportInput",
    "PrimaryCandidateContext",
    "Report",
    "ReportDocumentBuilder",
    "ReportDocument",
    "ReportDocumentContext",
    "build_system_cards",
    "humanize_signatures",
    "build_report_document",
    "build_report_document_data",
    "compose_report_document_context",
    "prepare_persisted_report_input",
    "prepare_report_input",
    "resolve_primary_report_candidate",
]
