"""Public PDF renderer facade.

This module keeps the historical import surface stable while delegating the
actual rendering work to focused modules for style, drawing, text, pagination,
and page composition.
"""

from __future__ import annotations

import logging

from .pdf_drawing import (
    _cert_display,
    _draw_footer,
    _draw_panel,
    _hex,
    _norm,
    _safe,
    _strength_with_peak,
)
from .pdf_engine import _build_canvas_pdf
from .pdf_page1 import _draw_next_steps_table, _draw_system_card, _page1
from .pdf_page2 import (
    _draw_additional_observations,
    _draw_pattern_evidence,
    _draw_peaks_table,
    _page2,
)
from .pdf_text import (
    _draw_kv,
    _draw_kv_column,
    _draw_section_block,
    _draw_text,
    _kv_consumed_height,
    _wrap_lines,
)
from .report_data import ReportTemplateData

LOGGER = logging.getLogger(__name__)

__all__ = [
    "build_report_pdf",
    "_build_canvas_pdf",
    "_cert_display",
    "_draw_additional_observations",
    "_draw_footer",
    "_draw_kv",
    "_draw_kv_column",
    "_draw_next_steps_table",
    "_draw_panel",
    "_draw_pattern_evidence",
    "_draw_peaks_table",
    "_draw_section_block",
    "_draw_system_card",
    "_draw_text",
    "_hex",
    "_kv_consumed_height",
    "_norm",
    "_page1",
    "_page2",
    "_safe",
    "_strength_with_peak",
    "_wrap_lines",
]


def build_report_pdf(data: ReportTemplateData) -> bytes:
    """Build a 2-page diagnostic-worksheet PDF from ReportTemplateData."""
    if not isinstance(data, ReportTemplateData):
        raise TypeError(f"build_report_pdf expects ReportTemplateData, got {type(data).__name__}")
    valid_tiers = frozenset({"A", "B", "C"})
    if data.certainty_tier_key not in valid_tiers:
        LOGGER.warning(
            "Invalid certainty_tier_key %r; falling back to 'C'.",
            data.certainty_tier_key,
        )
        data.certainty_tier_key = "C"
    try:
        return _build_canvas_pdf(data)
    except Exception as exc:
        LOGGER.error("PDF generation failed.", exc_info=True)
        raise RuntimeError(f"PDF generation failed: {type(exc).__name__}: {exc}") from exc
