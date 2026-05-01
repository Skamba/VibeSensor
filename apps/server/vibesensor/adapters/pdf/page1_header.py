"""Header and hero rendering for report page 1."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.page1_common import draw_label_value
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_BODY,
    FS_H2,
    FS_SMALL,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text, _measure_text_height, _truncate_single_line

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import Page1RenderPlan
    from vibesensor.shared.boundaries.reporting.document import VerdictPageData

__all__ = ["draw_header_strip", "draw_hero_block"]


def draw_header_strip(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    _draw_panel(
        c, x, y, w, h, fill=REPORT_COLORS["brand_surface"], border=REPORT_COLORS["brand_surface"]
    )
    c.setFillColor(_hex(REPORT_COLORS["brand"]))
    c.setFont(FONT_B, FS_BODY)
    c.drawString(x + 3 * mm, y + h - 4.2 * mm, plan.title or tr("REPORT_FOOTER_TITLE"))

    values = [
        (tr("RUN_DATE"), plan.run_datetime or tr("UNKNOWN")),
        (
            tr("CAR_LABEL"),
            " — ".join(part for part in (plan.car_name, plan.car_type) if part) or tr("UNKNOWN"),
        ),
        (tr("DURATION"), plan.duration_text or tr("UNKNOWN")),
        (tr("SENSORS_LABEL"), str(plan.sensor_count or 0)),
        (tr("SPEED_BAND"), plan.verdict_page.speed_window_label or tr("UNKNOWN")),
    ]
    inner_x = x + 3 * mm
    top_y = y + h - 9.0 * mm
    col_gap = 1.5 * mm
    col_w = (w - 6 * mm - (4 * col_gap)) / 5
    for index, (label, value) in enumerate(values):
        col = index
        col_x = inner_x + (col * (col_w + col_gap))
        row_y = top_y
        value_text = _truncate_single_line(str(value), col_w, FS_SMALL)
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_SMALL)
        c.drawString(col_x, row_y, label)
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_SMALL)
        _draw_text(
            c,
            col_x,
            row_y - 3.5 * mm,
            col_w,
            value_text,
            font=FONT_B,
            size=FS_SMALL,
            color=TEXT_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=1,
        )


def _status_palette(text: str, *, tr: Callable[..., str]) -> tuple[str, str]:
    if text == tr("REPORT_ACTION_STATUS_READY"):
        return (REPORT_COLORS["card_success_bg"], REPORT_COLORS["success"])
    if text == tr("REPORT_ACTION_STATUS_READY_CAUTION"):
        return (REPORT_COLORS["card_warn_bg"], REPORT_COLORS["warning"])
    if text == tr("REPORT_ACTION_STATUS_RECAPTURE"):
        return (REPORT_COLORS["card_error_bg"], REPORT_COLORS["danger"])
    return (REPORT_COLORS["card_neutral_bg"], REPORT_COLORS["card_neutral_border"])


def _draw_action_status_callout(
    c: Canvas,
    *,
    status: str,
    note: str | None,
    tr: Callable[..., str],
    x: float,
    y_top: float,
    w: float,
) -> None:
    fill, border = _status_palette(status, tr=tr)
    content_w = w - 6 * mm
    note_text = str(note or "").strip() or None
    card_h = 4.0 * mm + _measure_text_height(
        status,
        w=content_w,
        size=FS_SMALL,
        leading=FS_SMALL + 1.0,
        max_lines=2,
    )
    if note_text is not None:
        card_h += 0.4 * mm + _measure_text_height(
            note_text,
            w=content_w,
            size=FS_SMALL,
            leading=FS_SMALL + 1.1,
            max_lines=4,
        )
    card_h = float(max(12 * mm, card_h + 2.8 * mm))
    c.setFillColor(_hex(fill))
    c.setStrokeColor(_hex(border))
    c.roundRect(x, y_top - card_h + 1.2 * mm, w, card_h, 2.5 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(TEXT_CLR))
    text_y = _draw_text(
        c,
        x + 3 * mm,
        y_top - 3.2 * mm,
        content_w,
        status,
        font=FONT_B,
        size=FS_SMALL,
        color=TEXT_CLR,
        leading=FS_SMALL + 1.0,
        max_lines=2,
    )
    if note_text is not None:
        _draw_text(
            c,
            x + 3 * mm,
            text_y - 0.4 * mm,
            content_w,
            note_text,
            size=FS_SMALL,
            color=TEXT_CLR,
            leading=FS_SMALL + 1.1,
            max_lines=4,
        )


def draw_hero_block(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    verdict = plan.verdict_page
    _draw_panel(c, x, y, w, h, fill="#ffffff")
    inner_x = x + 5 * mm
    inner_y = y + h - 6.0 * mm
    content_w = w - 10 * mm

    next_y = draw_label_value(
        c,
        x=inner_x,
        y=inner_y,
        width=content_w,
        label=tr("REPORT_SUSPECTED_SOURCE_LABEL"),
        value=verdict.suspected_source or tr("UNKNOWN"),
        value_size=FS_H2,
    )
    if verdict.inspect_first:
        next_y = (
            _draw_text(
                c,
                inner_x,
                next_y - 0.2 * mm,
                content_w,
                f"{tr('REPORT_INSPECT_FIRST_LABEL')}: {verdict.inspect_first}",
                font=FONT_B,
                size=FS_BODY,
                color=TEXT_CLR,
                leading=FS_BODY + 1.1,
                max_lines=2,
            )
            - 0.8 * mm
        )
    if verdict.reason_sentence:
        _draw_text(
            c,
            inner_x,
            next_y - 0.2 * mm,
            content_w,
            verdict.reason_sentence,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.1,
            max_lines=2,
        )

    _draw_verdict_cues(c, verdict=verdict, tr=tr, x=inner_x, y=y + 22 * mm, w=content_w)
    if verdict.action_status_note:
        _draw_text(
            c,
            inner_x,
            y + 13.0 * mm,
            content_w,
            f"{tr('REPORT_PAGE1_MAIN_CAVEAT_LABEL')}: {verdict.action_status_note}",
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=1,
        )


def _draw_verdict_cues(
    c: Canvas,
    *,
    verdict: VerdictPageData,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
) -> None:
    status = str(verdict.action_status or tr("UNKNOWN")).strip()
    cue_texts = [status]
    if status == tr("REPORT_ACTION_STATUS_READY"):
        cue_texts.append(str(verdict.location_confidence or "").strip())
    cue_texts = [text for text in cue_texts if text]
    if not cue_texts:
        return

    row_gap = 1.2 * mm
    chip_h = 7.0 * mm
    cursor_x = x
    cursor_y = y + chip_h
    for index, text in enumerate(cue_texts[:3]):
        fill, border = _status_palette(text if index == 0 else "", tr=tr)
        chip_w = min(
            w, max(36 * mm, c.stringWidth(text, FONT_B if index == 0 else FONT, FS_SMALL) + 7 * mm)
        )
        if cursor_x != x and cursor_x + chip_w > x + w:
            cursor_x = x
            cursor_y -= chip_h + row_gap
        c.setFillColor(_hex(fill))
        c.setStrokeColor(_hex(border))
        c.roundRect(cursor_x, cursor_y - chip_h, chip_w, chip_h, 2.5 * mm, stroke=1, fill=1)
        _draw_text(
            c,
            cursor_x + 3 * mm,
            cursor_y - 2.2 * mm,
            chip_w - 6 * mm,
            text,
            font=FONT_B if index == 0 else FONT,
            size=FS_SMALL,
            color=TEXT_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=1,
        )
        cursor_x += chip_w + 1.8 * mm
