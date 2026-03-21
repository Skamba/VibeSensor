"""Additional-observations panel for PDF page 2."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import FONT, MUTED_CLR, SOFT_BG
from vibesensor.adapters.pdf.report_data import FindingPresentation


def _draw_additional_observations(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    transient_findings: list[FindingPresentation],
    tr: Callable[[str], str],
) -> None:
    """Draw transient-impact findings in the additional-observations panel."""
    _draw_panel(c, x, y, w, h, tr("ADDITIONAL_OBSERVATIONS"), fill=SOFT_BG)
    c.setFillColor(_hex(MUTED_CLR))
    c.setFont(FONT, 6.5)

    x_pad = x + 4 * mm
    step = 3.5 * mm
    y_min = y + 2 * mm
    y_cursor = y + h - 10 * mm
    for finding in transient_findings[:3]:
        if y_cursor < y_min:
            break
        order_label = finding.order.strip()
        if not order_label and finding.frequency_hz is not None:
            order_label = f"{finding.frequency_hz:.1f} Hz"
        if not order_label:
            order_label = tr("SOURCE_TRANSIENT_IMPACT")
        confidence = finding.effective_confidence
        c.drawString(x_pad, y_cursor, f"• {order_label} ({confidence * 100.0:.0f}%)")
        y_cursor -= step
