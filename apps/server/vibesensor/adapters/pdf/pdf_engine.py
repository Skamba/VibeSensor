"""Top-level PDF page orchestration and public report PDF builder."""

from __future__ import annotations

import logging
from io import BytesIO

from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_appendices import (
    _appendix_a_page,
    _appendix_c_page,
    worksheet_step_pages,
)
from vibesensor.adapters.pdf.pdf_drawing import _draw_footer
from vibesensor.adapters.pdf.pdf_page1 import _page1
from vibesensor.adapters.pdf.pdf_style import PAGE_SIZE, PdfRenderContext
from vibesensor.adapters.pdf.report_data import ReportTemplateData

LOGGER = logging.getLogger(__name__)


def build_report_pdf(data: ReportTemplateData) -> bytes:
    """Build the redesigned multi-page diagnostic report PDF."""
    if not isinstance(data, ReportTemplateData):
        raise TypeError(f"build_report_pdf expects ReportTemplateData, got {type(data).__name__}")
    valid_tiers = frozenset({"A", "B", "C"})
    if data.certainty_tier_key not in valid_tiers:
        LOGGER.warning(
            "Invalid certainty_tier_key %r; falling back to 'A'.",
            data.certainty_tier_key,
        )
        data.certainty_tier_key = "A"
    try:
        return _build_canvas_pdf(data)
    except Exception as exc:
        LOGGER.error("PDF generation failed.", exc_info=True)
        raise RuntimeError(f"PDF generation failed: {type(exc).__name__}: {exc}") from exc


def _build_canvas_pdf(data: ReportTemplateData) -> bytes:
    """Build the raw PDF bytes from *data* using the ReportLab Canvas API."""
    ctx = PdfRenderContext.from_data(data)

    buf = BytesIO()
    canvas = Canvas(buf, pagesize=PAGE_SIZE, pageCompression=0)
    canvas.setTitle(data.title or "VibeSensor Diagnostic Report")
    canvas.setAuthor("VibeSensor")
    canvas.setCreator("VibeSensor")
    canvas.setSubject("Vehicle vibration diagnostic report")
    recapture_mode = data.appendix_a.mode == "recapture"
    appendix_a_pages = (
        [[]] if recapture_mode else worksheet_step_pages(data.appendix_a, list(data.next_steps))
    )
    total_pages = 2 if recapture_mode else 2 + len(appendix_a_pages)

    _page1(canvas, data, ctx=ctx)
    _draw_footer(canvas, 1, total_pages, data.title)
    canvas.showPage()

    if recapture_mode:
        _appendix_a_page(canvas, data)
        _draw_footer(canvas, 2, total_pages, data.title)
    else:
        _appendix_c_page(canvas, data)
        _draw_footer(canvas, 2, total_pages, data.title)
        rendered_steps = 0
        for page_number, page_steps in enumerate(appendix_a_pages, start=3):
            canvas.showPage()
            _appendix_a_page(
                canvas,
                data,
                steps=page_steps,
                start_number=rendered_steps + 1,
                continued=page_number > 3,
            )
            _draw_footer(canvas, page_number, total_pages, data.title)
            rendered_steps += len(page_steps)

    canvas.save()
    return buf.getvalue()
