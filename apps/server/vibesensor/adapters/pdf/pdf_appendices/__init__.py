"""Appendix page composition for the redesigned diagnostic report PDF."""

from __future__ import annotations

from vibesensor.adapters.pdf.pdf_appendices.action_matrix import worksheet_step_pages
from vibesensor.adapters.pdf.pdf_appendices.appendix_b import _appendix_b_page
from vibesensor.adapters.pdf.pdf_appendices.appendix_c import _appendix_c_page
from vibesensor.adapters.pdf.pdf_appendices.layout import (
    _estimate_action_steps_panel_height,
    _estimate_appendix_c_context_panel_height,
    _estimate_appendix_c_suitability_panel_height,
    _estimate_appendix_c_trace_panel_height,
    _estimate_worksheet_ranked_stack_height,
    _estimate_worksheet_top_panel_height,
    _worksheet_first_actions_panel_height,
)
from vibesensor.adapters.pdf.pdf_appendices.title_bar import draw_appendix_title_bar
from vibesensor.adapters.pdf.pdf_appendices.worksheet import _appendix_a_page

__all__ = [
    "_appendix_a_page",
    "_appendix_b_page",
    "_appendix_c_page",
    "_estimate_action_steps_panel_height",
    "_estimate_appendix_c_context_panel_height",
    "_estimate_appendix_c_suitability_panel_height",
    "_estimate_appendix_c_trace_panel_height",
    "_estimate_worksheet_ranked_stack_height",
    "_estimate_worksheet_top_panel_height",
    "_worksheet_first_actions_panel_height",
    "draw_appendix_title_bar",
    "worksheet_step_pages",
]
