"""Top-level PDF page orchestration and public report PDF builder."""

from __future__ import annotations

from io import BytesIO
import logging

from reportlab.pdfgen.canvas import Canvas

from .pdf_drawing import _draw_footer
from .pdf_page1 import _page1
from .pdf_page2 import _page2
from .pdf_render_context import PdfRenderContext
from .pdf_style import PAGE_SIZE
from .report_data import ReportTemplateData

LOGGER = logging.getLogger(__name__)


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


def _build_canvas_pdf(data: ReportTemplateData) -> bytes:
    """Build the raw PDF bytes from *data* using the ReportLab Canvas API."""
    ctx = PdfRenderContext.from_data(data)

    buf = BytesIO()
    canvas = Canvas(buf, pagesize=PAGE_SIZE, pageCompression=0)

    remaining_next_steps = _page1(canvas, data, ctx=ctx)
    _draw_footer(canvas, 1, 2, data.version_marker)
    canvas.showPage()

    _page2(
        canvas,
        data,
        ctx=ctx,
        next_steps_continued=remaining_next_steps,
    )
    _draw_footer(canvas, 2, 2, data.version_marker)
    canvas.showPage()

    canvas.save()
    return buf.getvalue()
