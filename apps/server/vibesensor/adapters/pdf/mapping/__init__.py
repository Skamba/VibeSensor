"""Report mapping – thin mapper from prepared report inputs to template data."""

from __future__ import annotations

from vibesensor.adapters.pdf._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from vibesensor.adapters.pdf._card_builder import build_system_cards, humanize_signatures
from vibesensor.adapters.pdf.report_context import ReportMappingContext
from vibesensor.adapters.pdf.report_data import Report
from vibesensor.shared.boundaries.report_prepared_input import PreparedReportInput
from vibesensor.use_cases.history.report_preparation import prepare_report_input

from .pipeline import _build_report_template_data, map_summary
from .sections import (
    _build_appendix_a_data,
    _build_appendix_b_data,
    _build_appendix_c_data,
    _build_appendix_d_data,
    _build_timeline_graph_data,
    _build_verdict_page_data,
)

__all__ = [
    "PrimaryCandidateContext",
    "PreparedReportInput",
    "Report",
    "ReportMappingContext",
    "_build_appendix_a_data",
    "_build_appendix_b_data",
    "_build_appendix_c_data",
    "_build_appendix_d_data",
    "_build_report_template_data",
    "_build_timeline_graph_data",
    "_build_verdict_page_data",
    "build_system_cards",
    "humanize_signatures",
    "map_summary",
    "prepare_report_input",
    "resolve_primary_report_candidate",
]
