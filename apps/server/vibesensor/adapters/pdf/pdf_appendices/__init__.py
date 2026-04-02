"""Appendix page composition for the redesigned diagnostic report PDF."""

from __future__ import annotations

from .appendix_b import _appendix_b_page, _has_appendix_b_content
from .appendix_c import _appendix_c_page
from .appendix_d import _appendix_d_page
from .layout import (
    _estimate_action_steps_panel_height,
    _estimate_appendix_c_context_panel_height,
    _estimate_appendix_c_suitability_panel_height,
    _estimate_appendix_c_trace_panel_height,
    _estimate_worksheet_ranked_stack_height,
    _estimate_worksheet_top_panel_height,
    _worksheet_first_actions_panel_height,
)
from .worksheet import _appendix_a_page, worksheet_step_pages

__all__ = [
    "_appendix_a_page",
    "_appendix_b_page",
    "_appendix_c_page",
    "_appendix_d_page",
    "_estimate_action_steps_panel_height",
    "_estimate_appendix_c_context_panel_height",
    "_estimate_appendix_c_suitability_panel_height",
    "_estimate_appendix_c_trace_panel_height",
    "_estimate_worksheet_ranked_stack_height",
    "_estimate_worksheet_top_panel_height",
    "_has_appendix_b_content",
    "_worksheet_first_actions_panel_height",
    "worksheet_step_pages",
]
