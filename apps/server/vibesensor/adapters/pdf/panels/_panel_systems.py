"""Systems-with-findings panels for PDF page 1."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex, _safe
from vibesensor.adapters.pdf.pdf_style import (
    FONT_B,
    FS_BODY,
    FS_CARD_TITLE,
    GAP,
    MARGIN,
    PAGE_H,
    PANEL_HEADER_H,
    R_CARD,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
    build_page1_layout,
    observed_signature_row_count,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text
from vibesensor.adapters.pdf.report_data import ReportTemplateData, SystemFindingCard


def _compact_part_names(card: SystemFindingCard, fallback: str) -> str:
    names = [part.name.strip() for part in card.parts if part.name.strip()]
    return ", ".join(names[:3]) if names else fallback


def _draw_systems_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
) -> float:
    cards = data.system_cards[:2]
    n_cards = len(cards)
    layout = build_page1_layout(
        width=width,
        page_top=PAGE_H - MARGIN,
        header_content_height=0.0,
        observed_rows=observed_signature_row_count(
            certainty_tier_key=data.certainty_tier_key,
            system_card_count=len(data.system_cards),
            has_certainty_reason=bool(data.observed.certainty_reason),
        ),
    )
    cards_h = layout.systems.h
    cards_y = y_cursor - cards_h
    _draw_panel(c, MARGIN, cards_y, width, cards_h, tr("SYSTEMS_WITH_FINDINGS"))

    inner_x = MARGIN + 4 * mm
    inner_w = width - 8 * mm
    inner_top = cards_y + cards_h - PANEL_HEADER_H
    if data.certainty_tier_key == "A" or not cards:
        msg = (
            tr("TIER_A_NO_SYSTEMS")
            if data.certainty_tier_key == "A"
            else tr("NO_SYSTEMS_WITH_FINDINGS")
        )
        _draw_text(c, inner_x, inner_top, inner_w, msg, size=FS_BODY, color=SUB_CLR)
    else:
        card_gap = 3 * mm
        card_w = (inner_w - card_gap * max(n_cards - 1, 1)) / max(n_cards, 1)
        card_h = cards_h - 14 * mm
        for idx, card in enumerate(cards):
            cx = inner_x + idx * (card_w + card_gap)
            cy = cards_y + 3 * mm
            _draw_system_card(c, cx, cy, card_w, card_h, card, tr=tr)
    return float(cards_y - GAP)


def _draw_system_card(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    card: SystemFindingCard,
    *,
    tr: Callable[[str], str],
) -> None:
    """Render a single system-finding card."""
    na = tr("NOT_AVAILABLE")
    content_w = w - 6 * mm

    tone_bg = REPORT_COLORS.get(f"card_{card.tone}_bg", REPORT_COLORS["card_neutral_bg"])
    tone_border = REPORT_COLORS.get(
        f"card_{card.tone}_border",
        REPORT_COLORS["card_neutral_border"],
    )
    c.setFillColor(_hex(tone_bg))
    c.setStrokeColor(_hex(tone_border))
    c.roundRect(x, y, w, h, R_CARD, stroke=1, fill=1)

    cx = x + 3 * mm
    cy = y + h - 4 * mm
    title_bottom = _draw_text(
        c,
        cx,
        cy,
        content_w,
        card.system_name,
        font=FONT_B,
        size=FS_CARD_TITLE,
        color=TEXT_CLR,
        max_lines=2,
    )
    details_top = title_bottom - 1.2 * mm
    if card.status_label:
        details_top = (
            _draw_text(
                c,
                cx,
                title_bottom - 0.8 * mm,
                content_w,
                card.status_label,
                size=FS_BODY,
                color=SUB_CLR,
                max_lines=1,
            )
            - 1.0 * mm
        )

    if card.parts:
        pattern_bottom = _draw_text(
            c,
            cx,
            details_top,
            content_w,
            f"{tr('PATTERN_SUMMARY')}: {_safe(card.pattern_summary, na)}",
            size=FS_BODY,
            color=SUB_CLR,
            max_lines=2,
        )
        _draw_text(
            c,
            cx,
            pattern_bottom - 1.0 * mm,
            content_w,
            f"{tr('WHAT_TO_CHECK_FIRST')}: {_compact_part_names(card, na)}",
            size=FS_BODY,
            color=TEXT_CLR,
            max_lines=2,
        )
        return

    strongest_bottom = _draw_text(
        c,
        cx,
        details_top,
        content_w,
        f"{tr('STRONGEST_SENSOR')}: {_safe(card.strongest_location, na)}",
        size=FS_BODY,
        color=SUB_CLR,
        max_lines=2,
    )
    _draw_text(
        c,
        cx,
        strongest_bottom - 1.0 * mm,
        content_w,
        f"{tr('PATTERN_SUMMARY')}: {_safe(card.pattern_summary, na)}",
        size=FS_BODY,
        color=SUB_CLR,
        max_lines=2,
    )
