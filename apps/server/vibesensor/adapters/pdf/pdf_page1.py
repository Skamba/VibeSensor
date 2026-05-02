"""Page 1 composition for the redesigned diagnostic report PDF."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.page1_actions import draw_actions_block
from vibesensor.adapters.pdf.page1_header import draw_header_strip, draw_hero_block
from vibesensor.adapters.pdf.page1_proof import draw_proof_block
from vibesensor.adapters.pdf.pdf_style import GAP, MARGIN, PAGE_H, PAGE_W
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.types.json_types import JsonValue

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import Page1RenderPlan


def _page1(
    c: Canvas,
    plan: Page1RenderPlan,
) -> None:
    """Render the redesigned page-1 verdict surface."""
    width = PAGE_W - (2 * MARGIN)
    page_top = PAGE_H - MARGIN

    def tr(key: str, **kw: JsonValue) -> str:
        return _tr(plan.lang, key, **kw)

    header_h = 18 * mm
    hero_h = 64 * mm
    content_bottom = MARGIN + 3 * mm
    main_h = page_top - content_bottom - header_h - hero_h - (2 * GAP)
    lower_h = min(main_h, 176 * mm)
    lower_y = content_bottom + main_h - lower_h
    proof_w = width * 0.43
    actions_w = width - proof_w - GAP

    header_y = page_top - header_h
    hero_y = header_y - GAP - hero_h

    draw_header_strip(c, plan, tr=tr, x=MARGIN, y=header_y, w=width, h=header_h)
    draw_hero_block(c, plan, tr=tr, x=MARGIN, y=hero_y, w=width, h=hero_h)
    draw_proof_block(c, plan, tr=tr, x=MARGIN, y=lower_y, w=proof_w, h=lower_h)
    draw_actions_block(
        c,
        plan,
        tr=tr,
        x=MARGIN + proof_w + GAP,
        y=lower_y,
        w=actions_w,
        h=lower_h,
    )
