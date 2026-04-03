"""Canonical report-document assembly above the PDF renderer boundary."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import Report, ReportDocument
from vibesensor.use_cases.history.report_preparation import (
    prepare_persisted_report_input,
    prepare_report_input,
)

from ._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from ._card_builder import build_system_cards, humanize_signatures
from .assembly import ReportDocumentAssembly, assemble_report_document
from .builder import build_report_document
from .composition import ReportDocumentComposition, compose_report_document
from .sections import (
    _build_appendix_c_data,
    _build_appendix_d_data,
    _build_timeline_graph_data,
)

__all__ = [
    "PreparedReportInput",
    "PrimaryCandidateContext",
    "Report",
    "ReportDocumentComposition",
    "ReportDocumentAssembly",
    "ReportDocument",
    "_build_appendix_c_data",
    "_build_appendix_d_data",
    "_build_timeline_graph_data",
    "assemble_report_document",
    "build_system_cards",
    "humanize_signatures",
    "build_report_document",
    "compose_report_document",
    "prepare_persisted_report_input",
    "prepare_report_input",
    "resolve_primary_report_candidate",
]
