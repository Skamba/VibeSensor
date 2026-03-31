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

_STATUS_COLORS = {
    "Action-ready": (REPORT_COLORS["card_success_bg"], REPORT_COLORS["success"]),
    "Action-ready with caution": (REPORT_COLORS["card_warn_bg"], REPORT_COLORS["warning"]),
    "Recapture before acting": (REPORT_COLORS["card_error_bg"], REPORT_COLORS["danger"]),
}


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

    header_h = 18 * mm
    hero_h = 48 * mm
    footer_h = 17 * mm
    main_h = page_top - MARGIN - header_h - hero_h - footer_h - (3 * GAP)
    proof_w = width * 0.58
    actions_w = width - proof_w - GAP

    header_y = page_top - header_h
    hero_y = header_y - GAP - hero_h
    middle_y = hero_y - GAP - main_h
    footer_y = MARGIN + 8 * mm

    _draw_header_strip(c, data, tr=tr, x=MARGIN, y=header_y, w=width, h=header_h)
    _draw_hero_block(c, data, tr=tr, x=MARGIN, y=hero_y, w=width, h=hero_h)
    _draw_proof_block(c, data, tr=tr, x=MARGIN, y=middle_y, w=proof_w, h=main_h)
    _draw_actions_block(c, data, tr=tr, x=MARGIN + proof_w + GAP, y=middle_y, w=actions_w, h=main_h)
    _draw_route_footer(c, data, x=MARGIN, y=footer_y, w=width, h=footer_h)


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
    inner_y = y + h - 11.5 * mm
    col_w = (w - 8 * mm) / len(values)
    for index, (label, value) in enumerate(values):
        col_x = inner_x + (index * col_w)
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_SMALL)
        c.drawString(col_x, inner_y, label)
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_BODY)
        c.drawString(col_x, inner_y - 4.2 * mm, str(value))


def _draw_status_pill(c: Canvas, *, text: str, x: float, y: float) -> None:
    fill, border = _STATUS_COLORS.get(
        text,
        (REPORT_COLORS["card_neutral_bg"], REPORT_COLORS["card_neutral_border"]),
    )
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
    label: str,
    value: str,
    value_font: str = FONT_B,
    value_size: float = FS_TITLE,
) -> float:
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(x, y, label)
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(value_font, value_size)
    c.drawString(x, y - 5.0 * mm, value)
    return float(y - 9.5 * mm)


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
    left_w = w * 0.54

    next_y = _draw_label_value(
        c,
        x=inner_x,
        y=inner_y,
        label=tr("REPORT_SUSPECTED_SOURCE_LABEL"),
        value=verdict.suspected_source or tr("UNKNOWN"),
    )
    next_y = _draw_label_value(
        c,
        x=inner_x,
        y=next_y,
        label=tr("REPORT_INSPECT_FIRST_LABEL"),
        value=verdict.inspect_first or tr("UNKNOWN"),
    )

    status_x = x + left_w + 8 * mm
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(status_x, inner_y, tr("REPORT_ACTION_STATUS_LABEL"))
    _draw_status_pill(
        c, text=verdict.action_status or tr("UNKNOWN"), x=status_x, y=inner_y - 1.5 * mm
    )
    if verdict.action_status_note:
        _draw_text(
            c,
            status_x,
            inner_y - 9.0 * mm,
            w - (left_w + 13 * mm),
            verdict.action_status_note,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.1,
            max_lines=2,
        )

    reason_top = inner_y - 18.0 * mm
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(status_x, reason_top, tr("REPORT_WHY_THIS_IS_FIRST_LABEL"))
    _draw_text(
        c,
        status_x,
        reason_top - 4.8 * mm,
        w - (left_w + 13 * mm),
        verdict.reason_sentence or tr("UNKNOWN"),
        size=FS_BODY,
        color=TEXT_CLR,
        leading=FS_BODY + 1.5,
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
    _draw_panel(c, x, y, w, h, tr("REPORT_PROOF_PANEL_TITLE"))
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
    text_y = _draw_label_value(
        c,
        x=text_x,
        y=text_y,
        label=tr("REPORT_DOMINANT_CORNER_LABEL"),
        value=verdict.dominant_corner or tr("UNKNOWN"),
        value_size=FS_H2,
    )
    text_y = _draw_label_value(
        c,
        x=text_x,
        y=text_y,
        label=tr("REPORT_LOCATION_CONFIDENCE_LABEL"),
        value=verdict.location_confidence or tr("UNKNOWN"),
        value_size=FS_H2,
    )
    text_y = _draw_label_value(
        c,
        x=text_x,
        y=text_y,
        label=tr("REPORT_COVERAGE_LABEL"),
        value=verdict.coverage_label or tr("UNKNOWN"),
        value_size=FS_BODY,
    )
    if verdict.also_consider:
        text_y = _draw_label_value(
            c,
            x=text_x,
            y=text_y,
            label=tr("REPORT_ALSO_CONSIDER_LABEL"),
            value=verdict.also_consider,
            value_size=FS_BODY,
        )
    text_y = _draw_text(
        c,
        text_x,
        text_y,
        text_w,
        verdict.proof_summary or tr("UNKNOWN"),
        size=FS_BODY,
        color=TEXT_CLR,
        leading=FS_BODY + 1.5,
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
    body_parts = []
    if why:
        body_parts.append(f"{tr('WHY')}: {why}")
    if confirm:
        body_parts.append(f"{tr('CONFIRM')}: {confirm}")
    body = "\n".join(body_parts)
    text_w = w - 14 * mm
    title_lines = _wrap_lines(title, text_w, FS_BODY)[:2]
    body_lines = _wrap_lines(body, text_w, FS_SMALL)[:4] if body else []
    row_h = max(
        22 * mm,
        8.5 * mm + (len(title_lines) * (FS_BODY + 1.2)) + (len(body_lines) * (FS_SMALL + 1.2)),
    )
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
    if body:
        _draw_text(
            c,
            x + 12 * mm,
            title_y - 0.5 * mm,
            text_w,
            body,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.2,
            max_lines=4,
        )
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
        estimated_body = []
        if step.why:
            estimated_body.append(f"{tr('WHY')}: {step.why}")
        if step.confirm:
            estimated_body.append(f"{tr('CONFIRM')}: {step.confirm}")
        title_lines = _wrap_lines(step.action, (w - 22 * mm), FS_BODY)[:2]
        body_lines = (
            _wrap_lines("\n".join(estimated_body), (w - 22 * mm), FS_SMALL)[:4]
            if estimated_body
            else []
        )
        estimated_h = max(
            22 * mm,
            8.5 * mm + (len(title_lines) * (FS_BODY + 1.2)) + (len(body_lines) * (FS_SMALL + 1.2)),
        )
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
            why=step.why,
            confirm=step.confirm,
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
