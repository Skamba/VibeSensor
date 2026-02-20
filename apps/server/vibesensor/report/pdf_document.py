"""PDF document assembly helpers."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from typing import Any

from ..report_theme import REPORT_COLORS


def build_pdf_document(
    *,
    story: list[object],
    page_size: tuple[float, float],
    left_margin: int,
    right_margin: int,
    top_margin: int,
    bottom_margin: int,
    version_marker: str,
    tr: Callable[..., str],
) -> bytes:
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        pageCompression=0,
    )
    doc.title = f"VibeSensor Report {version_marker}"
    doc.subject = version_marker
    doc.author = "VibeSensor"

    def draw_footer(canvas: Any, document: Any) -> None:  # pragma: no cover - formatting callback
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor(REPORT_COLORS["text_muted"]))
        canvas.drawString(document.leftMargin, 12, tr("REPORT_FOOTER_TITLE"))
        canvas.drawCentredString(
            page_size[0] / 2.0,
            12,
            tr("PAGE_LABEL", page=canvas.getPageNumber()),
        )
        canvas.drawRightString(page_size[0] - document.rightMargin, 12, version_marker)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()
