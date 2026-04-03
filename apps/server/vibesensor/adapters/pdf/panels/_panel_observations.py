"""Additional-observations panel for PDF page 2."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import FONT, MUTED_CLR, SOFT_BG
from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.reporting.document import FindingPresentation


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
        c.drawString(x_pad, y_cursor, f"• {_observation_text(finding, tr=tr)}")
        y_cursor -= step


def _observation_text(
    finding: FindingPresentation,
    *,
    tr: Callable[[str], str],
) -> str:
    """Return a compact, human-readable transient observation summary."""
    source = str(finding.suspected_source or "").strip()
    parts = [human_source(source, tr=tr) if source else tr("SOURCE_TRANSIENT_IMPACT")]
    if finding.strongest_location:
        parts.append(str(finding.strongest_location))
    order_label = str(finding.order or "").strip()
    if order_label:
        parts.append(order_label)
    elif finding.frequency_hz is not None:
        parts.append(f"{finding.frequency_hz:.1f} Hz")
    return " | ".join(part for part in parts if part)
