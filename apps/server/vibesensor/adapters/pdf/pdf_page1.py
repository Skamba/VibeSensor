"""Page 1 composition for the redesigned diagnostic report PDF."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.page1_actions import draw_actions_block, estimate_actions_block_height
from vibesensor.adapters.pdf.page1_header import draw_header_strip, draw_hero_block
from vibesensor.adapters.pdf.page1_proof import draw_proof_block, draw_timeline_block
from vibesensor.adapters.pdf.pdf_style import GAP, MARGIN, PAGE_H, PAGE_W
from vibesensor.adapters.pdf.report_data import ReportTemplateData
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.types.json_types import JsonValue


def _page1(
    c: Canvas,
    data: ReportTemplateData,
    *,
    ctx: object | None = None,
) -> None:
    """Render the redesigned page-1 verdict surface."""
    del ctx
    width = PAGE_W - (2 * MARGIN)
    page_top = PAGE_H - MARGIN

    def tr(key: str, **kw: JsonValue) -> str:
        return _tr(data.lang, key, **kw)

    header_h = 26 * mm
    hero_h = 40 * mm
    content_bottom = MARGIN + 8 * mm
    main_h = page_top - content_bottom - header_h - hero_h - (2 * GAP)
    proof_w = width * 0.58
    actions_w = width - proof_w - GAP

    header_y = page_top - header_h
    hero_y = header_y - GAP - hero_h
    middle_y = content_bottom

    timeline_graph = data.verdict_page.timeline_graph
    timeline_gap = GAP if timeline_graph is not None else 0.0
    timeline_h = (
        float(min(48 * mm, max(42 * mm, main_h * 0.22))) if timeline_graph is not None else 0.0
    )
    upper_content_y = middle_y + timeline_h + timeline_gap
    upper_content_h = main_h - timeline_h - timeline_gap

    actions_h = min(upper_content_h, estimate_actions_block_height(data, tr=tr, w=actions_w))
    actions_y = upper_content_y + upper_content_h - actions_h

    draw_header_strip(c, data, tr=tr, x=MARGIN, y=header_y, w=width, h=header_h)
    draw_hero_block(c, data, tr=tr, x=MARGIN, y=hero_y, w=width, h=hero_h)
    draw_proof_block(c, data, tr=tr, x=MARGIN, y=upper_content_y, w=proof_w, h=upper_content_h)
    draw_actions_block(
        c,
        data,
        tr=tr,
        x=MARGIN + proof_w + GAP,
        y=actions_y,
        w=actions_w,
        h=actions_h,
    )
    if timeline_graph is not None:
        draw_timeline_block(c, data, tr=tr, x=MARGIN, y=middle_y, w=width, h=timeline_h)
