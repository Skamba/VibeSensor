"""Header and hero rendering for report page 1."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.shared.boundaries.reporting.document import ReportTemplateData
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
from vibesensor.adapters.pdf.pdf_text import _draw_text, _measure_text_height

__all__ = ["draw_header_strip", "draw_hero_block"]


def draw_header_strip(
    c: Canvas,
    data: ReportTemplateData,
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
    c.setFont(FONT_B, FS_H2)
    c.drawString(x + 4 * mm, y + h - 5.5 * mm, data.title or tr("REPORT_FOOTER_TITLE"))

    values = [
        (tr("RUN_DATE"), data.run_datetime or tr("UNKNOWN")),
        (
            tr("CAR_LABEL"),
            " — ".join(part for part in (data.car_name, data.car_type) if part) or tr("UNKNOWN"),
        ),
        (tr("DURATION"), data.duration_text or tr("UNKNOWN")),
        (tr("SENSORS_LABEL"), str(data.sensor_count or 0)),
        (tr("SPEED_BAND"), data.verdict_page.speed_window_label or tr("UNKNOWN")),
    ]
    inner_x = x + 4 * mm
    top_y = y + h - 12.0 * mm
    col_gap = 2 * mm
    col_w = (w - 8 * mm - (2 * col_gap)) / 3
    for index, (label, value) in enumerate(values):
        row = index // 3
        col = index % 3
        col_x = inner_x + (col * (col_w + col_gap))
        row_y = top_y - (row * 8.2 * mm)
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_SMALL)
        c.drawString(col_x, row_y, label)
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_BODY)
        _draw_text(
            c,
            col_x,
            row_y - 4.0 * mm,
            col_w,
            str(value),
            font=FONT_B,
            size=FS_BODY,
            color=TEXT_CLR,
            leading=FS_BODY + 1.0,
            max_lines=2,
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
    data: ReportTemplateData,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    verdict = data.verdict_page
    _draw_panel(c, x, y, w, h, fill="#ffffff")
    inner_x = x + 5 * mm
    inner_y = y + h - 6.0 * mm
    left_w = w * 0.58
    left_content_w = left_w - 10 * mm
    right_x = x + left_w + 8 * mm
    right_w = w - (left_w + 13 * mm)

    next_y = draw_label_value(
        c,
        x=inner_x,
        y=inner_y,
        width=left_content_w,
        label=tr("REPORT_SUSPECTED_SOURCE_LABEL"),
        value=verdict.suspected_source or tr("UNKNOWN"),
    )
    if verdict.inspect_first:
        next_y = (
            _draw_text(
                c,
                inner_x,
                next_y - 0.2 * mm,
                left_content_w,
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
            left_content_w,
            verdict.reason_sentence,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.1,
            max_lines=4,
        )

    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(right_x, inner_y + 1.2 * mm, tr("REPORT_ACTION_STATUS_LABEL"))
    _draw_action_status_callout(
        c,
        status=verdict.action_status or tr("UNKNOWN"),
        note=verdict.action_status_note,
        tr=tr,
        x=right_x,
        y_top=inner_y - 1.5 * mm,
        w=right_w,
    )
