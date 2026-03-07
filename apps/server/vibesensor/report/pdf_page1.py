"""Page 1 composition for the diagnostic worksheet PDF."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from ..report_i18n import tr as _tr
from .pdf_drawing import _draw_panel, _hex, _safe
from .pdf_page1_sections import (
    build_header_rows as _build_header_rows_impl,
)
from .pdf_page1_sections import (
    column_height as _column_height_impl,
)
from .pdf_page1_sections import (
    label_width as _label_width_impl,
)
from .pdf_page1_sections import (
    render_bottom_row_panels as _render_bottom_row_panels_impl,
)
from .pdf_page1_sections import (
    render_header_panel as _render_header_panel_impl,
)
from .pdf_page1_sections import (
    render_observed_signature_panel as _render_observed_signature_panel_impl,
)
from .pdf_page1_sections import (
    render_systems_panel as _render_systems_panel_impl,
)
from .pdf_render_context import PdfRenderContext
from .pdf_style import (
    DATA_TRUST_LABEL_W,
    FONT,
    FONT_B,
    FS_BODY,
    FS_CARD_TITLE,
    FS_SMALL,
    LINE_CLR,
    PANEL_BG,
    PANEL_HEADER_H,
    SOFT_BG,
    SUB_CLR,
    TEXT_CLR,
)
from .pdf_text import _draw_kv, _draw_text
from .report_data import NextStep, ReportTemplateData, SystemFindingCard
from .theme import REPORT_COLORS


def _label_width(c: Canvas, label: str, *, default_w: float, col_w: float) -> float:
    return _label_width_impl(c, label, default_w=default_w, col_w=col_w)


def _column_height(
    rows: list[tuple[str, str, float]], *, available_w: float, row_gap: float
) -> float:
    return _column_height_impl(rows, available_w=available_w, row_gap=row_gap)


def _build_header_rows(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    columns,
    na: str,
) -> tuple[list[tuple[str, str, float]], list[tuple[str, str, float]], float, float, float]:
    return _build_header_rows_impl(c, data, tr=tr, columns=columns, na=na)


def _draw_header_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    page_top: float,
    na: str,
) -> float:
    return _render_header_panel_impl(c, data, tr=tr, width=width, page_top=page_top, na=na)


def _draw_observed_signature_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
    na: str,
) -> float:
    return _render_observed_signature_panel_impl(
        c,
        data,
        tr=tr,
        width=width,
        y_cursor=y_cursor,
        na=na,
    )


def _draw_systems_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
) -> float:
    return _render_systems_panel_impl(
        c,
        data,
        tr=tr,
        width=width,
        y_cursor=y_cursor,
        draw_system_card=_draw_system_card,
    )


def _draw_data_trust_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    x: float,
    y: float,
    w: float,
    h: float,
    na: str,
) -> None:
    _draw_panel(c, x, y, w, h, tr("DATA_TRUST"))
    tx = x + 4 * mm
    ty = y + h - PANEL_HEADER_H
    trust_val_w = w - 8 * mm - DATA_TRUST_LABEL_W
    if data.data_trust:
        for item in data.data_trust[:6]:
            icon = "\u2713" if item.state == "pass" else "\u26a0"
            state_lbl = tr("PASS") if item.state == "pass" else tr("WARN_SHORT")
            value = f"{icon} {state_lbl}"
            if item.state != "pass" and item.detail:
                value = f"{icon} {item.detail}"
            new_ty = _draw_kv(
                c,
                tx,
                ty,
                item.check,
                value,
                label_w=DATA_TRUST_LABEL_W,
                fs=FS_SMALL,
                value_w=trust_val_w,
            )
            ty = new_ty - 1.0 * mm
    else:
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_SMALL)
        c.drawString(tx, ty, na)


def _draw_bottom_row_panels(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
    na: str,
) -> list[NextStep]:
    return _render_bottom_row_panels_impl(
        c,
        data,
        tr=tr,
        width=width,
        y_cursor=y_cursor,
        na=na,
        draw_next_steps_table=_draw_next_steps_table,
    )


def _page1(
    c: Canvas, data: ReportTemplateData, *, ctx: PdfRenderContext | None = None
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
    # Data Trust remains the bottom-right panel on page 1.
    return _draw_bottom_row_panels(c, data, tr=tr, width=width, y_cursor=y_cursor, na=na)


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

    tone_bg = REPORT_COLORS.get(f"card_{card.tone}_bg", REPORT_COLORS["card_neutral_bg"])
    tone_border = REPORT_COLORS.get(
        f"card_{card.tone}_border", REPORT_COLORS["card_neutral_border"]
    )
    c.setFillColor(_hex(tone_bg))
    c.setStrokeColor(_hex(tone_border))
    c.roundRect(x, y, w, h, 4, stroke=1, fill=1)

    cx = x + 3 * mm
    cy = y + h - 4 * mm
    title_bottom = _draw_text(
        c,
        cx,
        cy,
        w - 6 * mm,
        card.system_name,
        font=FONT_B,
        size=FS_CARD_TITLE,
        color=TEXT_CLR,
        max_lines=2,
    )
    strongest_bottom = _draw_text(
        c,
        cx,
        title_bottom - 1.2 * mm,
        w - 6 * mm,
        f"{tr('STRONGEST_SENSOR')}: {_safe(card.strongest_location, na)}",
        size=FS_BODY,
        color=SUB_CLR,
        max_lines=2,
    )
    pattern_bottom = _draw_text(
        c,
        cx,
        strongest_bottom - 1.0 * mm,
        w - 6 * mm,
        _safe(card.pattern_summary, na),
        size=FS_BODY,
        color=SUB_CLR,
        max_lines=2,
    )

    if card.parts:
        parts_y = pattern_bottom - 1.0 * mm
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_BODY)
        c.drawString(cx, parts_y, tr("COMMON_PARTS"))

        py = parts_y - 3.6 * mm
        for part in card.parts[:3]:
            if py <= y + 3 * mm:
                break
            py = _draw_text(
                c,
                cx,
                py,
                w - 6 * mm,
                f"\u2022 {part.name}",
                size=FS_BODY,
                color=TEXT_CLR,
                max_lines=2,
            )
            py -= 0.8 * mm


def _draw_next_steps_table(
    c: Canvas,
    x: float,
    y_top: float,
    w: float,
    y_bottom: float,
    steps: list[NextStep],
    *,
    start_number: int = 1,
) -> int:
    """Draw ordered next-step rows with multi-line wrapping."""
    from . import pdf_builder as pdf_builder_module

    col1_w = 12 * mm
    text_w = w - col1_w - 4
    min_row_h = 6.6 * mm
    fs = 7
    leading = fs + 2

    soft_bg = _hex(SOFT_BG)
    panel_bg = _hex(PANEL_BG)
    line_clr = _hex(LINE_CLR)
    text_clr = _hex(TEXT_CLR)
    row_pad = 2 * mm
    number_y_off = 4.4 * mm

    y = y_top
    drawn = 0
    for idx, step in enumerate(steps, start=start_number):
        action_text = step.action
        if step.why:
            action_text += f" \u2014 {step.why}"
        if step.confirm:
            action_text += f"  \u2713 {step.confirm}"
        if step.falsify:
            action_text += f"  \u2717 {step.falsify}"
        if step.eta:
            action_text += f"  \u23f1 {step.eta}"

        lines = pdf_builder_module._wrap_lines(action_text, text_w, fs)
        row_h = max(min_row_h, max(len(lines), 1) * leading + row_pad)
        if y - row_h < y_bottom:
            break

        c.setFillColor(soft_bg if idx % 2 == 0 else panel_bg)
        c.setStrokeColor(line_clr)
        c.rect(x, y - row_h, w, row_h, stroke=1, fill=1)

        c.setFillColor(text_clr)
        c.setFont(FONT_B, fs)
        c.drawString(x + 2, y - number_y_off, f"{idx}.")

        pdf_builder_module._draw_text(
            c,
            x + col1_w,
            y - 2 * mm,
            text_w,
            action_text,
            font=FONT,
            size=fs,
            color=TEXT_CLR,
        )
        y -= row_h
        drawn += 1
    return drawn
