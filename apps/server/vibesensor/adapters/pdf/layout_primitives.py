"""Small ReportLab layout primitives internal to the PDF adapter."""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FS_BODY,
    FS_SMALL,
    LINE_CLR,
    PANEL_BG,
    PANEL_HEADER_H,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import (
    _draw_section_block,
    _draw_text,
    _measure_section_block_height,
)

__all__ = [
    "PanelRegion",
    "draw_overflow_note_if_room",
    "draw_panel_region",
    "draw_section_block_if_room",
    "draw_text_block",
]


@dataclass(frozen=True, slots=True)
class PanelRegion:
    """Content geometry for a drawn PDF panel."""

    x: float
    y: float
    w: float
    h: float
    inset: float = 4 * mm
    top_gap: float = 2 * mm

    @property
    def content_x(self) -> float:
        return float(self.x + self.inset)

    @property
    def content_w(self) -> float:
        return float(max(0.0, self.w - (2 * self.inset)))

    @property
    def content_top(self) -> float:
        return float(self.y + self.h - PANEL_HEADER_H - self.top_gap)

    @property
    def content_bottom(self) -> float:
        return float(self.y + self.inset)


def draw_panel_region(
    c: Canvas,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str | None = None,
    inset: float = 4 * mm,
    top_gap: float = 2 * mm,
    fill: str = PANEL_BG,
    border: str = LINE_CLR,
) -> PanelRegion:
    """Draw a standard panel and return its reusable content region."""

    _draw_panel(c, x, y, w, h, title, fill=fill, border=border)
    return PanelRegion(x=x, y=y, w=w, h=h, inset=inset, top_gap=top_gap)


def draw_text_block(
    c: Canvas,
    *,
    region: PanelRegion,
    y: float,
    text: str,
    font: str = FONT,
    size: float = FS_BODY,
    color: str = TEXT_CLR,
    leading: float | None = None,
    max_lines: int | None = None,
    after_gap: float = 0.0,
) -> float:
    """Draw wrapped text inside a panel region and return the next y position."""

    return float(
        _draw_text(
            c,
            region.content_x,
            y,
            region.content_w,
            text,
            font=font,
            size=size,
            color=color,
            leading=leading,
            max_lines=max_lines,
        )
        - after_gap
    )


def draw_section_block_if_room(
    c: Canvas,
    *,
    region: PanelRegion,
    y: float,
    title: str,
    body: str,
    max_lines: int,
) -> tuple[float, bool]:
    """Draw a title/body block only when it fits in the panel region."""

    needed_h = _measure_section_block_height(body, w=region.content_w, max_lines=max_lines)
    if y - needed_h < region.content_bottom:
        return y, False
    return (
        _draw_section_block(
            c,
            region.content_x,
            y,
            region.content_w,
            title,
            body,
            max_lines=max_lines,
        ),
        True,
    )


def draw_overflow_note_if_room(
    c: Canvas,
    *,
    region: PanelRegion,
    y: float,
    text: str,
    size: float = FS_SMALL,
    color: str = SUB_CLR,
    leading: float | None = None,
    max_lines: int = 2,
    min_height: float = 6 * mm,
    after_gap: float = 0.8 * mm,
) -> float:
    """Draw a compact overflow note when there is enough vertical room."""

    if y - min_height < region.content_bottom:
        return y
    if leading is None:
        leading = size + 1.0
    return draw_text_block(
        c,
        region=region,
        y=y,
        text=text,
        size=size,
        color=color,
        leading=leading,
        max_lines=max_lines,
        after_gap=after_gap,
    )
