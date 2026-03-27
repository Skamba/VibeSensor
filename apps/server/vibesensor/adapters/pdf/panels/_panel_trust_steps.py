"""Data-trust and next-steps panels for the PDF report."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    DATA_TRUST_LABEL_W,
    FONT,
    FONT_B,
    FS_BODY,
    FS_SMALL,
    LINE_CLR,
    MARGIN,
    PAGE_H,
    PAGE_W,
    PANEL_BG,
    PANEL_HEADER_H,
    SOFT_BG,
    SUB_CLR,
    TEXT_CLR,
    build_page1_layout,
    build_page2_layout,
    observed_signature_row_count,
)
from vibesensor.adapters.pdf.pdf_text import _draw_kv, _draw_text, _wrap_lines
from vibesensor.adapters.pdf.report_data import NextStep, ReportTemplateData


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
            icon = "✓" if item.state == "pass" else "⚠"
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


def _draw_next_steps_table(
    c: Canvas,
    x: float,
    y_top: float,
    w: float,
    y_bottom: float,
    steps: list[NextStep],
    *,
    start_number: int = 1,
    tr: Callable[[str], str],
) -> int:
    """Draw ordered next-step rows with a primary action and secondary details."""
    col1_w = 12 * mm
    text_w = w - col1_w - 4
    min_row_h = 7.2 * mm
    action_fs = 7.5
    action_leading = action_fs + 1.5
    detail_fs = FS_SMALL
    detail_leading = detail_fs + 1.5

    soft_bg = _hex(SOFT_BG)
    panel_bg = _hex(PANEL_BG)
    line_clr = _hex(LINE_CLR)
    text_clr = _hex(TEXT_CLR)
    row_pad = 1.5 * mm
    number_y_off = 4.0 * mm
    detail_gap = 0.4 * mm

    y = y_top
    drawn = 0
    for idx, step in enumerate(steps, start=start_number):
        detail_parts: list[str] = []
        if step.why:
            detail_parts.append(f"{tr('WHY')}: {step.why}")
        if step.eta:
            eta_text = f"{tr('ETA')}: {step.eta}"
            if step.confirm:
                detail_parts.append(f"{tr('CONFIRM')}: {step.confirm}")
            detail_parts.append(eta_text)
        elif step.confirm:
            detail_parts.append(f"{tr('CONFIRM')}: {step.confirm}")
        detail_text = " | ".join(detail_parts)

        action_lines = _wrap_lines(step.action, text_w, action_fs)
        detail_line_count = len(_wrap_lines(detail_text, text_w, detail_fs)) if detail_text else 0
        detail_h = detail_line_count * detail_leading if detail_line_count else 0.0
        row_h = max(
            min_row_h,
            max(len(action_lines), 1) * action_leading
            + detail_h
            + row_pad
            + (detail_gap if detail_text else 0.0),
        )
        if y - row_h < y_bottom:
            break

        c.setFillColor(soft_bg if idx % 2 == 0 else panel_bg)
        c.setStrokeColor(line_clr)
        c.rect(x, y - row_h, w, row_h, stroke=1, fill=1)

        c.setFillColor(text_clr)
        c.setFont(FONT_B, action_fs)
        c.drawString(x + 2, y - number_y_off, f"{idx}.")

        action_bottom = _draw_text(
            c,
            x + col1_w,
            y - 2 * mm,
            text_w,
            step.action,
            font=FONT_B,
            size=action_fs,
            color=TEXT_CLR,
        )
        if detail_text:
            _draw_text(
                c,
                x + col1_w,
                action_bottom - detail_gap,
                text_w,
                detail_text,
                font=FONT,
                size=detail_fs,
                color=SUB_CLR,
                leading=detail_leading,
            )
        y -= row_h
        drawn += 1
    return drawn


def _draw_bottom_row_panels(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
    na: str,
) -> list[NextStep]:
    layout = build_page1_layout(
        width=width,
        page_top=PAGE_H - MARGIN,
        header_content_height=0.0,
        observed_rows=observed_signature_row_count(
            certainty_tier_key=data.certainty_tier_key,
            system_card_count=len(data.system_cards),
            has_certainty_reason=bool(data.observed.certainty_reason),
        ),
        y_after_systems_source=y_cursor,
    )
    next_panel = layout.bottom.next_steps
    trust_panel = layout.bottom.data_trust

    _draw_panel(c, next_panel.x, next_panel.y, next_panel.w, next_panel.h, tr("NEXT_STEPS"))
    nx = next_panel.x + 4 * mm
    ny = next_panel.y + next_panel.h - 11 * mm
    if not data.next_steps:
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_BODY)
        c.drawString(nx, ny, tr("NO_NEXT_STEPS"))
        remaining_next_steps: list[NextStep] = []
    else:
        drawn_steps = _draw_next_steps_table(
            c,
            nx,
            ny,
            next_panel.w - 8 * mm,
            next_panel.y + 3 * mm,
            data.next_steps,
            tr=tr,
        )
        remaining_next_steps = data.next_steps[drawn_steps:]

    _draw_data_trust_panel(
        c,
        data,
        tr=tr,
        x=trust_panel.x,
        y=trust_panel.y,
        w=trust_panel.w,
        h=trust_panel.h,
        na=na,
    )
    return remaining_next_steps


def _draw_continued_next_steps(
    c: Canvas,
    *,
    y_top: float,
    next_steps_continued: list[NextStep],
    start_number: int,
    tr: Callable[[str], str],
) -> None:
    layout = build_page2_layout(
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
        has_transient_findings=y_top < (PAGE_H - MARGIN),
        has_next_steps_continued=True,
    )
    if layout.continued_next_steps is None:
        return

    panel = layout.continued_next_steps
    _draw_panel(c, panel.x, panel.y, panel.w, panel.h, tr("NEXT_STEPS"))
    _draw_next_steps_table(
        c,
        panel.x + 4 * mm,
        panel.y + panel.h - 11 * mm,
        panel.w - 8 * mm,
        panel.y + 3 * mm,
        next_steps_continued,
        start_number=start_number,
        tr=tr,
    )
