"""Page 1 composition for the redesigned diagnostic report PDF."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_BODY,
    FS_H2,
    FS_SMALL,
    FS_TITLE,
    GAP,
    MARGIN,
    PAGE_H,
    PAGE_W,
    PANEL_HEADER_H,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text, _wrap_lines
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

    _draw_header_strip(c, data, tr=tr, x=MARGIN, y=header_y, w=width, h=header_h)
    _draw_hero_block(c, data, tr=tr, x=MARGIN, y=hero_y, w=width, h=hero_h)
    _draw_proof_block(c, data, tr=tr, x=MARGIN, y=middle_y, w=proof_w, h=main_h)
    _draw_actions_block(c, data, tr=tr, x=MARGIN + proof_w + GAP, y=middle_y, w=actions_w, h=main_h)


def _draw_header_strip(
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
        (
            tr("SPEED_BAND"),
            data.verdict_page.speed_window_label or tr("UNKNOWN"),
        ),
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


def _draw_status_pill(c: Canvas, *, text: str, tr: Callable[..., str], x: float, y: float) -> None:
    fill, border = _status_palette(text, tr=tr)
    text_w = c.stringWidth(text, FONT_B, FS_SMALL)
    pill_w = max(32 * mm, text_w + (6 * mm))
    pill_h = 7 * mm
    c.setFillColor(_hex(fill))
    c.setStrokeColor(_hex(border))
    c.roundRect(x, y - pill_h + 1.2 * mm, pill_w, pill_h, 3 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(x + 3 * mm, y - 3.5 * mm, text)


def _draw_label_value(
    c: Canvas,
    *,
    x: float,
    y: float,
    width: float | None,
    label: str,
    value: str,
    value_font: str = FONT_B,
    value_size: float = FS_TITLE,
    max_lines: int = 2,
) -> float:
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(x, y, label)
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(value_font, value_size)
    if width is None:
        c.drawString(x, y - 5.0 * mm, value)
        return float(y - 9.5 * mm)
    value_lines = _wrap_lines(value, width, value_size)[:max_lines] or [value]
    line_y = y - 5.0 * mm
    line_leading = value_size + 1.0
    for line in value_lines:
        c.drawString(x, line_y, line)
        line_y -= line_leading
    return float(line_y - 1.8 * mm)


def _draw_hero_block(
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
    left_w = w * 0.52
    left_content_w = left_w - 10 * mm
    right_x = x + left_w + 8 * mm
    right_w = w - (left_w + 13 * mm)

    next_y = _draw_label_value(
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

    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(right_x, inner_y, tr("REPORT_ACTION_STATUS_LABEL"))
    _draw_status_pill(
        c,
        text=verdict.action_status or tr("UNKNOWN"),
        tr=tr,
        x=right_x,
        y=inner_y - 1.5 * mm,
    )
    if verdict.action_status_note:
        note_fill, note_border = _status_palette(verdict.action_status or tr("UNKNOWN"), tr=tr)
        note_lines = _wrap_lines(verdict.action_status_note, right_w - 6 * mm, FS_SMALL)[:3]
        note_h = max(10 * mm, 4 * mm + (len(note_lines) * (FS_SMALL + 1.1)))
        note_top = inner_y - 9.0 * mm
        c.setFillColor(_hex(note_fill))
        c.setStrokeColor(_hex(note_border))
        c.roundRect(
            right_x,
            note_top - note_h + 1.2 * mm,
            right_w,
            note_h,
            2.5 * mm,
            stroke=1,
            fill=1,
        )
        _draw_text(
            c,
            right_x + 3 * mm,
            note_top - 2.0 * mm,
            right_w - 6 * mm,
            verdict.action_status_note,
            size=FS_SMALL,
            color=TEXT_CLR,
            leading=FS_SMALL + 1.1,
            max_lines=3,
        )


def _draw_proof_block(
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
    _draw_panel(c, x, y, w, h, verdict.proof_panel_title or tr("REPORT_PROOF_PANEL_TITLE"))
    inner_x = x + 4 * mm
    inner_y = y + h - PANEL_HEADER_H - 2 * mm
    diagram_w = w * 0.55
    diagram_h = h - 20 * mm
    diagram = car_location_diagram(
        data.top_causes or data.findings,
        {
            "sensor_locations": data.sensor_locations,
            "sensor_intensity_by_location": data.sensor_intensity_by_location,
        },
        data.location_hotspot_rows,
        content_width=w - 8 * mm,
        tr=tr,
        text_fn=lambda en, nl: nl if data.lang == "nl" else en,
        diagram_width=diagram_w - 2 * mm,
        diagram_height=diagram_h - 8 * mm,
    )
    diagram.drawOn(c, inner_x, y + 7 * mm)

    text_x = x + diagram_w + 4 * mm
    text_w = w - diagram_w - 8 * mm
    text_y = inner_y
    text_y = (
        _draw_text(
            c,
            text_x,
            text_y,
            text_w,
            verdict.proof_summary or tr("UNKNOWN"),
            font=FONT_B,
            size=FS_BODY,
            color=TEXT_CLR,
            leading=FS_BODY + 1.4,
            max_lines=4,
        )
        - 1.5 * mm
    )
    text_y = _draw_label_value(
        c,
        x=text_x,
        y=text_y,
        width=text_w,
        label=tr("REPORT_DOMINANT_CORNER_LABEL"),
        value=verdict.dominant_corner or tr("UNKNOWN"),
        value_size=FS_H2,
    )
    text_y = _draw_label_value(
        c,
        x=text_x,
        y=text_y,
        width=text_w,
        label=tr("REPORT_LOCATION_CONFIDENCE_LABEL"),
        value=verdict.location_confidence or tr("UNKNOWN"),
        value_size=FS_H2,
    )
    text_y = _draw_label_value(
        c,
        x=text_x,
        y=text_y,
        width=text_w,
        label=tr("REPORT_COVERAGE_LABEL"),
        value=verdict.coverage_label or tr("UNKNOWN"),
        value_size=FS_BODY,
        max_lines=3,
    )
    if verdict.also_consider:
        text_y = _draw_label_value(
            c,
            x=text_x,
            y=text_y,
            width=text_w,
            label=tr("REPORT_ALTERNATIVE_SOURCE_LABEL"),
            value=verdict.also_consider,
            value_size=FS_BODY,
        )
    if verdict.proof_caveat:
        _draw_text(
            c,
            text_x,
            text_y - 1.5 * mm,
            text_w,
            verdict.proof_caveat,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.2,
        )


def _draw_action_row(
    c: Canvas,
    *,
    tr: Callable[..., str],
    x: float,
    y_top: float,
    w: float,
    index: int,
    title: str,
    why: str | None,
    confirm: str | None,
) -> float:
    text_w = w - 14 * mm
    title_lines = _wrap_lines(title, text_w, FS_BODY)[:2]
    row_h = max(16 * mm, 8.5 * mm + (len(title_lines) * (FS_BODY + 1.2)))
    c.setFillColor(_hex(REPORT_COLORS["surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["border"]))
    c.roundRect(x, y_top - row_h, w, row_h, 3 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(REPORT_COLORS["brand_surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["brand_surface"]))
    c.roundRect(x + 2 * mm, y_top - 9.5 * mm, 7 * mm, 7 * mm, 2 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(REPORT_COLORS["brand"]))
    c.setFont(FONT_B, FS_SMALL)
    c.drawCentredString(x + 5.5 * mm, y_top - 6.4 * mm, str(index))
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_BODY)
    title_y = y_top - 5.4 * mm
    for line in title_lines:
        c.drawString(x + 12 * mm, title_y, line)
        title_y -= FS_BODY + 1.2
    return float(y_top - row_h - 2.5 * mm)


def _draw_actions_block(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    _draw_panel(c, x, y, w, h, tr("REPORT_ACTIONS_PANEL_TITLE"))
    inner_x = x + 4 * mm
    inner_y = y + h - PANEL_HEADER_H - 2 * mm
    if not data.next_steps:
        _draw_text(
            c, inner_x, inner_y, w - 8 * mm, tr("NO_NEXT_STEPS"), size=FS_BODY, color=SUB_CLR
        )
        return
    row_y = inner_y
    for index, step in enumerate(data.next_steps[:3], start=1):
        title_lines = _wrap_lines(step.action, (w - 22 * mm), FS_BODY)[:2]
        estimated_h = max(16 * mm, 8.5 * mm + (len(title_lines) * (FS_BODY + 1.2)))
        if row_y - estimated_h < y + 4 * mm:
            break
        row_y = _draw_action_row(
            c,
            tr=tr,
            x=inner_x,
            y_top=row_y,
            w=w - 8 * mm,
            index=index,
            title=step.action,
            why=None,
            confirm=None,
        )


def _draw_route_footer(
    c: Canvas,
    data: ReportTemplateData,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    _draw_panel(c, x, y, w, h, fill=REPORT_COLORS["surface"], border=REPORT_COLORS["border"])
    routes = list(data.verdict_page.footer_routes)
    if not routes:
        return
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    inner_x = x + 4 * mm
    top = y + h - 5.0 * mm
    col_w = (w - 8 * mm) / 2
    for index, route in enumerate(routes[:4]):
        col = index % 2
        row = index // 2
        c.drawString(inner_x + (col * col_w), top - (row * 4.5 * mm), route)
