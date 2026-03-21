"""Page 1 composition for the diagnostic worksheet PDF."""

from __future__ import annotations

from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf._panel_header import (
    _draw_header_panel,
    _draw_observed_signature_panel,
)
from vibesensor.adapters.pdf._panel_systems import _draw_systems_panel
from vibesensor.adapters.pdf._panel_trust_steps import _draw_bottom_row_panels
from vibesensor.adapters.pdf.pdf_style import PdfRenderContext
from vibesensor.adapters.pdf.report_data import NextStep, ReportTemplateData
from vibesensor.report_i18n import tr as _tr


def _page1(
    c: Canvas,
    data: ReportTemplateData,
    *,
    ctx: PdfRenderContext | None = None,
) -> list[NextStep]:
    """Render the full page-1 worksheet layout."""
    render_ctx = ctx or PdfRenderContext.from_data(data)
    width = render_ctx.width
    page_top = render_ctx.page_top

    def tr(key: str) -> str:
        return _tr(data.lang, key)

    na = tr("UNKNOWN")
    y_cursor = _draw_header_panel(c, data, tr=tr, width=width, page_top=page_top, na=na)
    y_cursor = _draw_observed_signature_panel(c, data, tr=tr, width=width, y_cursor=y_cursor, na=na)
    y_cursor = _draw_systems_panel(c, data, tr=tr, width=width, y_cursor=y_cursor)
    return _draw_bottom_row_panels(c, data, tr=tr, width=width, y_cursor=y_cursor, na=na)
