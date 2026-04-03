"""Top-level PDF page orchestration and public report PDF builder."""

from __future__ import annotations

import logging
from io import BytesIO

from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_appendices import (
    _appendix_a_page,
    _appendix_b_page,
    _appendix_c_page,
)
from vibesensor.adapters.pdf.pdf_drawing import _draw_footer
from vibesensor.adapters.pdf.pdf_page1 import _page1
from vibesensor.adapters.pdf.pdf_style import PAGE_SIZE
from vibesensor.adapters.pdf.report_types import build_report_render_plan
from vibesensor.shared.boundaries.reporting.document import ReportDocument

LOGGER = logging.getLogger(__name__)


def build_report_pdf(data: ReportDocument) -> bytes:
    """Build the redesigned multi-page diagnostic report PDF."""
    if not isinstance(data, ReportDocument):
        raise TypeError(f"build_report_pdf expects ReportDocument, got {type(data).__name__}")
    valid_tiers = frozenset({"A", "B", "C"})
    if data.certainty_tier_key not in valid_tiers:
        LOGGER.warning(
            "Invalid certainty_tier_key %r; falling back to 'A'.",
            data.certainty_tier_key,
        )
        data.certainty_tier_key = "A"
    return _build_canvas_pdf(data)


def _build_canvas_pdf(data: ReportDocument) -> bytes:
    """Build the raw PDF bytes from *data* using the ReportLab Canvas API."""
    plan = build_report_render_plan(data)

    buf = BytesIO()
    canvas = Canvas(buf, pagesize=PAGE_SIZE, pageCompression=0)
    canvas.setTitle(plan.document_title)
    canvas.setAuthor("VibeSensor")
    canvas.setCreator("VibeSensor")
    canvas.setSubject("Vehicle vibration diagnostic report")
    _page1(canvas, plan.page1)
    _draw_footer(canvas, 1, plan.total_pages, plan.document_title)
    canvas.showPage()

    if plan.recapture_mode:
        _appendix_a_page(canvas, plan.appendix_a_pages[0])
        _draw_footer(canvas, 2, plan.total_pages, plan.document_title)
    else:
        current_page = 2
        if plan.appendix_b is not None:
            _appendix_b_page(canvas, plan.appendix_b)
            _draw_footer(canvas, current_page, plan.total_pages, plan.document_title)
            canvas.showPage()
            current_page += 1
        _appendix_c_page(canvas, plan.appendix_c)
        _draw_footer(canvas, current_page, plan.total_pages, plan.document_title)
        first_appendix_a_page = current_page + 1
        for page_number, appendix_page in enumerate(
            plan.appendix_a_pages, start=first_appendix_a_page
        ):
            canvas.showPage()
            _appendix_a_page(canvas, appendix_page)
            _draw_footer(canvas, page_number, plan.total_pages, plan.document_title)

    canvas.save()
    return buf.getvalue()
