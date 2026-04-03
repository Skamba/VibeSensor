"""Data-trust and next-steps panels for the PDF report."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
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
from vibesensor.adapters.pdf.pdf_text import _draw_text, _wrap_lines
from vibesensor.shared.boundaries.reporting.document import NextStep, ReportTemplateData


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
    content_w = w - 8 * mm
    if data.data_trust:
        warn_items = [item for item in data.data_trust if item.state != "pass"]
        pass_items = [item for item in data.data_trust if item.state == "pass"]

        if data.certainty_tier_key == "A":
            confidence_level = tr("CONFIDENCE_LOW")
            confidence_effect = tr("DATA_TRUST_EFFECT_LOW")
            effect_color = TEXT_CLR
        elif data.certainty_tier_key == "B" or warn_items:
            confidence_level = tr("CONFIDENCE_MEDIUM")
            confidence_effect = tr("DATA_TRUST_EFFECT_MEDIUM")
            effect_color = TEXT_CLR
        else:
            confidence_level = tr("CONFIDENCE_HIGH")
            confidence_effect = tr("DATA_TRUST_EFFECT_HIGH")
            effect_color = SUB_CLR

        summary_title = f"{tr('CONFIDENCE_LABEL')}: {confidence_level}"
        summary_bottom = _draw_text(
            c,
            tx,
            ty,
            content_w,
            summary_title,
            font=FONT_B,
            size=FS_BODY,
            color=TEXT_CLR,
        )
        ty = (
            _draw_text(
                c,
                tx,
                summary_bottom - 0.4 * mm,
                content_w,
                confidence_effect,
                font=FONT,
                size=FS_SMALL,
                color=effect_color,
            )
            - 0.9 * mm
        )

        if warn_items:
            ty = (
                _draw_text(
                    c,
                    tx,
                    ty,
                    content_w,
                    tr("DATA_TRUST_CAVEATS"),
                    font=FONT_B,
                    size=FS_SMALL,
                    color=TEXT_CLR,
                )
                - 0.5 * mm
            )
            visible_warn_items = warn_items[:3]
            for item in visible_warn_items:
                detail = item.detail or tr("WARN_SHORT")
                ty = (
                    _draw_text(
                        c,
                        tx,
                        ty,
                        content_w,
                        f"{item.check}: {detail}",
                        font=FONT,
                        size=FS_SMALL,
                        color=TEXT_CLR,
                    )
                    - 0.6 * mm
                )
            extra_warn_count = len(warn_items) - len(visible_warn_items)
            if extra_warn_count > 0:
                ty = (
                    _draw_text(
                        c,
                        tx,
                        ty,
                        content_w,
                        f"+{extra_warn_count} {tr('DATA_TRUST_MORE_CAVEATS')}",
                        font=FONT,
                        size=FS_SMALL,
                        color=SUB_CLR,
                    )
                    - 0.6 * mm
                )

        if pass_items:
            passed_checks = ", ".join(item.check for item in pass_items)
            _draw_text(
                c,
                tx,
                ty,
                content_w,
                f"{tr('DATA_TRUST_CHECKS_PASSED')}: {passed_checks}",
                font=FONT,
                size=FS_SMALL,
                color=SUB_CLR,
            )
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
    first_row_extra_pad = 1.0 * mm
    first_row_number_pad_x = 2.0 * mm
    default_number_pad_x = 2.0
    first_row_top_pad = 3.0 * mm
    default_top_pad = 2.0 * mm
    detail_gap = 0.4 * mm

    y = y_top
    drawn = 0
    for idx, step in enumerate(steps, start=start_number):
        is_first_row = drawn == 0
        number_pad_x = first_row_number_pad_x if is_first_row else default_number_pad_x
        row_top_pad = first_row_top_pad if is_first_row else default_top_pad
        number_y_off = row_top_pad + (2.0 * mm)
        detail_parts: list[str] = []
        if step.why:
            detail_parts.append(f"{tr('WHY')}: {step.why}")
        if step.confirm:
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
            + (first_row_extra_pad if is_first_row else 0.0)
            + (detail_gap if detail_text else 0.0),
        )
        if y - row_h < y_bottom:
            break

        c.setFillColor(soft_bg if idx % 2 == 0 else panel_bg)
        c.setStrokeColor(line_clr)
        c.rect(x, y - row_h, w, row_h, stroke=1, fill=1)

        c.setFillColor(text_clr)
        c.setFont(FONT_B, action_fs)
        c.drawString(x + number_pad_x, y - number_y_off, f"{idx}.")

        action_bottom = _draw_text(
            c,
            x + col1_w,
            y - row_top_pad,
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
