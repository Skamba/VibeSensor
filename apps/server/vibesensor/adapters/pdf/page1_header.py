"""Header and hero rendering for report page 1."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_BODY,
    FS_SMALL,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text, _truncate_single_line

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import Page1RenderPlan
    from vibesensor.shared.boundaries.reporting.document import VerdictPageData

__all__ = ["draw_header_strip", "draw_hero_block"]

HERO_SOURCE_SIZE = 20.0
HERO_INSPECT_SIZE = 14.5
HERO_REASON_SIZE = 8.0
HERO_DECISION_LABEL_SIZE = 6.6
HERO_DECISION_VALUE_SIZE = 7.8


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
        c,
        x,
        y,
        w,
        h,
        fill=REPORT_COLORS["brand_surface_soft"],
        border=REPORT_COLORS["brand_surface_soft"],
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
    col_weights = [1.05, 1.30, 0.78, 0.62, 1.55]
    col_unit = (w - 6 * mm - (4 * col_gap)) / sum(col_weights)
    col_x = inner_x
    for index, (label, value) in enumerate(values):
        col_w = col_unit * col_weights[index]
        row_y = top_y
        value_lines = 2 if index == 4 else 1
        value_text = (
            str(value) if value_lines > 1 else _truncate_single_line(str(value), col_w, FS_SMALL)
        )
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
            max_lines=value_lines,
        )
        col_x += col_w + col_gap


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
    content_w = w - 10 * mm
    status = str(verdict.action_status or tr("UNKNOWN")).strip()
    decision_w = min(66 * mm, content_w * 0.34)
    text_w = content_w - decision_w - 7 * mm

    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(inner_x, y + h - 8.0 * mm, tr("REPORT_SUSPECTED_SOURCE_LABEL"))
    _draw_text(
        c,
        inner_x,
        y + h - 17.0 * mm,
        text_w,
        verdict.suspected_source or tr("UNKNOWN"),
        font=FONT_B,
        size=HERO_SOURCE_SIZE,
        color=TEXT_CLR,
        leading=HERO_SOURCE_SIZE + 1.0,
        max_lines=1,
    )
    if verdict.inspect_first:
        _draw_text(
            c,
            inner_x,
            y + h - 31.0 * mm,
            text_w,
            f"{tr('REPORT_INSPECT_FIRST_LABEL')}: {verdict.inspect_first}",
            font=FONT_B,
            size=HERO_INSPECT_SIZE,
            color=TEXT_CLR,
            leading=HERO_INSPECT_SIZE + 2.0,
            max_lines=2,
        )
    if verdict.reason_sentence:
        _draw_text(
            c,
            inner_x,
            y + h - 45.0 * mm,
            text_w,
            verdict.reason_sentence,
            size=HERO_REASON_SIZE,
            color=SUB_CLR,
            leading=HERO_REASON_SIZE + 1.1,
            max_lines=3,
        )

    decision_h = 45.0 * mm
    _draw_decision_path_card(
        c,
        verdict=verdict,
        status=status,
        tr=tr,
        x=inner_x + text_w + 7 * mm,
        y=y + h - 8.5 * mm - decision_h,
        w=decision_w,
        h=decision_h,
    )


def _draw_decision_path_card(
    c: Canvas,
    *,
    verdict: VerdictPageData,
    status: str,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    rows = []
    if status:
        rows.append((tr("REPORT_ACTION_STATUS_LABEL"), status))
    if verdict.fallback_path:
        rows.append((tr("REPORT_IF_PRIMARY_CLEAN_LABEL"), verdict.fallback_path))
    elif verdict.action_status_note:
        rows.append((tr("REPORT_PAGE1_DECISION_NOTE_LABEL"), verdict.action_status_note))
    location_confidence = str(verdict.location_confidence or "").strip()
    limited_confidence = tr("REPORT_LOCATION_CONFIDENCE_LIMITED")
    if location_confidence and location_confidence != limited_confidence:
        rows.append((tr("REPORT_LOCATION_CONFIDENCE_LABEL"), location_confidence))
    rows = [(label, str(value).strip()) for label, value in rows if str(value).strip()]
    if not rows:
        return

    c.setFillColor(_hex(REPORT_COLORS["surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
    c.roundRect(x, y, w, h, 3 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(x + 3 * mm, y + h - 4.5 * mm, tr("REPORT_PAGE1_DECISION_PATH_TITLE"))

    row_gap = 1.0 * mm
    row_top = y + h - 8.6 * mm
    row_h = (h - 11.5 * mm - ((len(rows) - 1) * row_gap)) / len(rows)
    row_h = max(8.0 * mm, min(13.2 * mm, row_h))
    for label, value in rows[:3]:
        row_y = row_top - row_h
        c.setFillColor(_hex("#ffffff"))
        c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
        c.roundRect(x + 2.5 * mm, row_y, w - 5 * mm, row_h, 2.2 * mm, stroke=1, fill=1)
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, HERO_DECISION_LABEL_SIZE)
        c.drawString(x + 5 * mm, row_y + row_h - 3.1 * mm, label)
        _draw_text(
            c,
            x + 5 * mm,
            row_y + row_h - 6.0 * mm,
            w - 10 * mm,
            value,
            font=FONT_B,
            size=HERO_DECISION_VALUE_SIZE,
            color=TEXT_CLR,
            leading=HERO_DECISION_VALUE_SIZE + 0.8,
            max_lines=2,
        )
        row_top = row_y - row_gap
