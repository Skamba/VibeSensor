"""ReportLab renderer: one function per page, drawing a ``ReportView`` with built-in Helvetica.

Layout only. Every string and number comes from ``report/view_model.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from math import ceil, floor, inf, log10

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm as _mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from vibesensor.report.view_model import (
    CarDiagram,
    Fact,
    MechanicPage,
    OwnerPage,
    OwnerTone,
    QualitySection,
    ReportView,
    SpectrumChart,
    SpeedChart,
)

__all__ = ["render_report_pdf"]

MM: float = float(_mm)
PAGE_W, PAGE_H = float(A4[0]), float(A4[1])
MARGIN = 14 * MM
CONTENT_W = PAGE_W - 2 * MARGIN
FONT = "Helvetica"
BOLD = "Helvetica-Bold"
GAP = 4 * MM
_CONTENT_BOTTOM = MARGIN + 4 * MM  # keeps clear of the footer line
_CHART_H = 52 * MM
_CHART_MIN_H = 34 * MM

INK = colors.HexColor("#1a1c24")
MUTED = colors.HexColor("#5b5e68")
LINE = colors.HexColor("#c9ccd4")
SURFACE = colors.HexColor("#f4f5f8")
BRAND = colors.HexColor("#6d28d9")
BRAND_SOFT = colors.HexColor("#ede9fe")
GOOD = colors.HexColor("#0f7b45")
GOOD_SOFT = colors.HexColor("#e5f4ec")
WARN = colors.HexColor("#a15c07")
WARN_SOFT = colors.HexColor("#fdf1dc")
BAD = colors.HexColor("#b42318")
BAD_SOFT = colors.HexColor("#fde8e6")
GREY_SOFT = colors.HexColor("#eceef2")
SERIES = (BRAND, colors.HexColor("#8a8f9c"), colors.HexColor("#b4b8c2"), colors.HexColor("#d4d7de"))

_HEADER_COLUMNS = 3


def render_report_pdf(view: ReportView) -> bytes:
    """Render the owner page, the workshop page, and a third page only when needed.

    The third page carries the workshop charts when they do not fit on page 2,
    and the data-quality section when any check warns. When every check passes,
    data quality is one footer line on the last page.
    """
    charts_on_page2 = _charts_fit_on_workshop_page(view.mechanic)
    third_page = not charts_on_page2 or not view.quality.all_passed
    total = 3 if third_page else 2
    footer_line = view.quality.footer_line if view.quality.all_passed else None

    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, pageCompression=1)
    canvas.setTitle(view.title)
    canvas.setAuthor("VibeSensor")
    canvas.setCreator("VibeSensor")
    _owner_page(canvas, view.owner, _header_band(canvas, view))
    _footer(canvas, view, 1, total, None)
    canvas.showPage()
    _mechanic_page(canvas, view.mechanic, with_charts=charts_on_page2)
    _footer(canvas, view, 2, total, None if third_page else footer_line)
    if third_page:
        canvas.showPage()
        y = PAGE_H - MARGIN
        if not charts_on_page2:
            y = _charts(canvas, view.mechanic, y, _CHART_H)
        if not view.quality.all_passed:
            _quality_section(canvas, view.quality, y)
        _footer(canvas, view, 3, total, footer_line)
    canvas.save()
    return buffer.getvalue()


# -- text primitives ---------------------------------------------------------------


def _lines(text: str, font: str, size: float, width: float) -> list[str]:
    return simpleSplit(text, font, size, width) or [""]


def _paragraph(
    canvas: Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = FONT,
    size: float = 9,
    color: colors.Color = INK,
    leading: float | None = None,
) -> float:
    """Draw wrapped text with its first baseline at ``y``; return the y below it."""
    leading = leading or size * 1.32
    canvas.setFont(font, size)
    canvas.setFillColor(color)
    for line in _lines(text, font, size, width):
        canvas.drawString(x, y, line)
        y -= leading
    return y


def _paragraph_height(text: str, width: float, *, font: str = FONT, size: float = 9) -> float:
    return len(_lines(text, font, size, width)) * size * 1.32


def _section_title(canvas: Canvas, text: str, x: float, y: float) -> float:
    canvas.setFont(BOLD, 10.5)
    canvas.setFillColor(INK)
    canvas.drawString(x, y, text)
    return y - 5.5 * MM


def _box(
    canvas: Canvas,
    x: float,
    y_top: float,
    width: float,
    height: float,
    *,
    fill: colors.Color = SURFACE,
    stroke: colors.Color | None = None,
) -> None:
    canvas.setFillColor(fill)
    canvas.setStrokeColor(stroke or fill)
    canvas.roundRect(x, y_top - height, width, height, 2.5 * MM, stroke=1, fill=1)


def _bullets(
    canvas: Canvas,
    items: Sequence[str],
    x: float,
    y: float,
    width: float,
    *,
    size: float = 9,
    numbered: bool = True,
) -> float:
    for index, item in enumerate(items, start=1):
        canvas.setFont(BOLD, size)
        canvas.setFillColor(INK)
        canvas.drawString(x, y, f"{index}." if numbered else "\u2022")
        y = _paragraph(canvas, item, x + 4.5 * MM, y, width - 4.5 * MM, size=size) - 0.8 * MM
    return y


def _facts_grid(
    canvas: Canvas,
    facts: Sequence[Fact],
    x: float,
    y: float,
    width: float,
    *,
    columns: int,
    label_size: float = 7,
    value_size: float = 9,
) -> float:
    """Label-over-value cells, ``columns`` per row; return the y below the grid."""
    cell_w = width / columns
    for row_start in range(0, len(facts), columns):
        row = facts[row_start : row_start + columns]
        heights = []
        for index, fact in enumerate(row):
            cx = x + index * cell_w
            canvas.setFont(FONT, label_size)
            canvas.setFillColor(MUTED)
            canvas.drawString(cx, y, fact.label)
            end = _paragraph(
                canvas,
                fact.value,
                cx,
                y - value_size * 1.25,
                cell_w - 3 * MM,
                font=BOLD,
                size=value_size,
            )
            heights.append(y - end)
        y -= max(heights) + 1.5 * MM
    return y


@dataclass(frozen=True, slots=True)
class _Column:
    width: float
    bold: bool = False


def _table(
    canvas: Canvas,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    x: float,
    y: float,
    columns: Sequence[_Column],
    *,
    size: float = 8,
    highlight: Sequence[bool] = (),
) -> float:
    """Simple ruled table with wrapping cells; return the y below it."""
    total_w = sum(column.width for column in columns)
    pad = 1.6 * MM
    leading = size * 1.25

    def draw_row(cells: Sequence[str], top: float, *, header_row: bool, shade: bool) -> float:
        wrapped = [
            _lines(cell, BOLD if header_row or column.bold else FONT, size, column.width - 2 * pad)
            for cell, column in zip(cells, columns, strict=True)
        ]
        height = max(len(lines) for lines in wrapped) * leading + 2 * pad - (leading - size)
        if header_row or shade:
            canvas.setFillColor(GREY_SOFT if header_row else BRAND_SOFT)
            canvas.rect(x, top - height, total_w, height, stroke=0, fill=1)
        cx = x
        for lines, column in zip(wrapped, columns, strict=True):
            canvas.setFont(BOLD if header_row or column.bold else FONT, size)
            canvas.setFillColor(MUTED if header_row else INK)
            ly = top - pad - size
            for line in lines:
                canvas.drawString(cx + pad, ly, line)
                ly -= leading
            cx += column.width
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(x, top - height, x + total_w, top - height)
        return top - height

    y = draw_row(header, y, header_row=True, shade=False)
    for index, row in enumerate(rows):
        y = draw_row(row, y, header_row=False, shade=index < len(highlight) and highlight[index])
    return y


def _footer(canvas: Canvas, view: ReportView, page: int, total: int, line: str | None) -> None:
    canvas.setFont(FONT, 7)
    canvas.setFillColor(MUTED)
    y = MARGIN - 6 * MM
    if line:
        lines = _lines(line, FONT, 7, CONTENT_W - 30 * MM)
        canvas.drawString(MARGIN, y + 3.2 * MM if len(lines) > 1 else y, lines[0])
        if len(lines) > 1:
            canvas.drawString(MARGIN, y, lines[1])
    else:
        canvas.drawString(MARGIN, y, view.title)
    canvas.drawRightString(PAGE_W - MARGIN, y, view.page_label(page, total))


# -- page 1 --------------------------------------------------------------------------


def _facts_grid_height(
    facts: Sequence[Fact],
    width: float,
    *,
    columns: int,
    value_size: float = 9,
) -> float:
    """Height ``_facts_grid`` will use for *facts*."""
    cell_w = width / columns
    total = 0.0
    for row_start in range(0, len(facts), columns):
        row = facts[row_start : row_start + columns]
        total += (
            max(
                value_size * 1.25
                + _paragraph_height(fact.value, cell_w - 3 * MM, font=BOLD, size=value_size)
                for fact in row
            )
            + 1.5 * MM
        )
    return total


def _header_band(canvas: Canvas, view: ReportView) -> float:
    top = PAGE_H - MARGIN
    inner_w = CONTENT_W - 8 * MM
    height = 14 * MM + _facts_grid_height(view.header, inner_w, columns=_HEADER_COLUMNS)
    _box(canvas, MARGIN, top, CONTENT_W, height, fill=BRAND_SOFT)
    canvas.setFont(BOLD, 13)
    canvas.setFillColor(BRAND)
    canvas.drawString(MARGIN + 4 * MM, top - 7 * MM, view.title)
    _facts_grid(
        canvas, view.header, MARGIN + 4 * MM, top - 12.5 * MM, inner_w, columns=_HEADER_COLUMNS
    )
    return top - height - GAP


_TONE_COLORS: dict[OwnerTone, tuple[colors.Color, colors.Color]] = {
    "good": (GOOD, GOOD_SOFT),
    "strong": (BAD, BAD_SOFT),
    "moderate": (WARN, WARN_SOFT),
    "muted": (MUTED, GREY_SOFT),
}


def _verdict_box(canvas: Canvas, owner: OwnerPage, y: float) -> float:
    accent, soft = _TONE_COLORS[owner.tone]
    inner_w = CONTENT_W - 10 * MM
    texts = [(owner.headline, BOLD, 15), (owner.description, FONT, 10.5)]
    if owner.candidate:
        texts.append((owner.candidate, BOLD, 10.5))
    has_level = bool(owner.level_word and owner.level_meaning)
    height = 8 * MM + sum(
        _paragraph_height(text, inner_w, font=font, size=size) for text, font, size in texts
    )
    if has_level:
        height += 7 * MM
    _box(canvas, MARGIN, y, CONTENT_W, height, fill=soft)
    canvas.setFillColor(accent)
    canvas.rect(MARGIN, y - height, 1.6 * MM, height, stroke=0, fill=1)
    ty = y - 8 * MM
    ty = _paragraph(
        canvas, owner.headline, MARGIN + 6 * MM, ty, inner_w, font=BOLD, size=15, color=accent
    )
    if has_level:
        _confidence_chip(canvas, owner, MARGIN + 6 * MM, ty - 1 * MM, accent)
        ty -= 7 * MM
    ty = _paragraph(canvas, owner.description, MARGIN + 6 * MM, ty - 0.5 * MM, inner_w, size=10.5)
    if owner.candidate:
        _paragraph(canvas, owner.candidate, MARGIN + 6 * MM, ty, inner_w, font=BOLD, size=10.5)
    return y - height - GAP


def _confidence_chip(
    canvas: Canvas, owner: OwnerPage, x: float, y: float, accent: colors.Color
) -> None:
    label = f"{owner.level_word}"
    meaning = f"{owner.level_meaning}"
    canvas.setFont(FONT, 9)
    canvas.setFillColor(MUTED)
    canvas.drawString(x, y, owner.confidence_label)
    x += canvas.stringWidth(owner.confidence_label, FONT, 9) + 2 * MM
    canvas.setFont(BOLD, 9)
    label_w = canvas.stringWidth(label, BOLD, 9) + 5 * MM
    canvas.setFillColor(accent)
    canvas.roundRect(x, y - 1.6 * MM, label_w, 5.2 * MM, 1.5 * MM, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.drawString(x + 2.5 * MM, y, label)
    canvas.setFillColor(INK)
    canvas.setFont(FONT, 9)
    canvas.drawString(x + label_w + 2 * MM, y, meaning)


def _owner_page(canvas: Canvas, owner: OwnerPage, y: float) -> None:
    y = _verdict_box(canvas, owner, y)
    diagram_w = 62 * MM
    text_w = CONTENT_W - diagram_w - GAP
    _car_diagram(canvas, owner.diagram, MARGIN + text_w + GAP, y, diagram_w, 112 * MM)
    x = MARGIN
    if owner.reasons_title and owner.reasons:
        y = _section_title(canvas, owner.reasons_title, x, y - 2 * MM)
        y = _bullets(canvas, owner.reasons, x, y, text_w) - 2 * MM
    if owner.covered_title and owner.covered:
        y = _section_title(canvas, owner.covered_title, x, y - 2 * MM)
        y = _paragraph(canvas, owner.covered, x, y, text_w) - 1 * MM
    if owner.not_covered_title and owner.not_covered:
        y = _section_title(canvas, owner.not_covered_title, x, y - 2 * MM)
        y = _bullets(canvas, owner.not_covered, x, y, text_w, numbered=False) - 1 * MM
    if owner.confirm_title and owner.confirm:
        y = _step_box(
            canvas, owner.confirm_title, owner.confirm, None, x, y - 2 * MM, text_w, WARN_SOFT
        )
    if owner.recapture_title and owner.recapture:
        y = _section_title(canvas, owner.recapture_title, x, y - 2 * MM)
        y = _bullets(canvas, owner.recapture, x, y, text_w) - 2 * MM
    else:
        y = _step_box(
            canvas,
            owner.next_step_title,
            owner.next_step,
            owner.fallback_step,
            x,
            y - 2 * MM,
            text_w,
            SURFACE,
        )
    if owner.verify_title and owner.verify:
        y = _section_title(canvas, owner.verify_title, x, y - 2 * MM)
        _paragraph(canvas, owner.verify, x, y, text_w)


def _step_box(
    canvas: Canvas,
    title: str,
    body: str,
    fallback: str | None,
    x: float,
    y: float,
    width: float,
    fill: colors.Color,
) -> float:
    inner = width - 8 * MM
    height = 11 * MM + _paragraph_height(body, inner, font=BOLD, size=11)
    if fallback:
        height += _paragraph_height(fallback, inner, size=10) + 1.5 * MM
    _box(canvas, x, y, width, height, fill=fill)
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(x + 4 * MM, y - 5 * MM, title.upper())
    ty = _paragraph(canvas, body, x + 4 * MM, y - 10 * MM, inner, font=BOLD, size=11)
    if fallback:
        _paragraph(canvas, fallback, x + 4 * MM, ty - 1.5 * MM, inner, size=10, color=MUTED)
    return y - height - GAP


# -- car diagram -----------------------------------------------------------------------

# Normalized (x, y from the front) positions on a top-view car.
_POSITIONS: dict[str, tuple[float, float]] = {
    "front_left_wheel": (0.10, 0.20),
    "front_right_wheel": (0.90, 0.20),
    "rear_left_wheel": (0.10, 0.80),
    "rear_right_wheel": (0.90, 0.80),
    "engine_bay": (0.50, 0.13),
    "front_subframe": (0.50, 0.25),
    "transmission": (0.50, 0.34),
    "driveshaft_tunnel": (0.50, 0.52),
    "driver_seat": (0.32, 0.45),
    "front_passenger_seat": (0.68, 0.45),
    "rear_left_seat": (0.30, 0.64),
    "rear_center_seat": (0.50, 0.66),
    "rear_right_seat": (0.70, 0.64),
    "rear_subframe": (0.50, 0.76),
    "trunk": (0.50, 0.90),
}
_WHEEL_CODES = ("front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel")
# Zone rectangles (x0, y0, x1, y1) in the same normalized space.
_ZONE_RECTS: dict[str, tuple[float, float, float, float]] = {
    "engine_bay": (0.14, 0.04, 0.86, 0.27),
    "driveshaft_tunnel": (0.42, 0.28, 0.58, 0.80),
    "transmission": (0.36, 0.27, 0.64, 0.40),
    "front_axle": (0.14, 0.16, 0.86, 0.24),
    "rear_axle": (0.14, 0.76, 0.86, 0.84),
}


@dataclass(frozen=True, slots=True)
class _DiagramLabel:
    """Where one marker's level label goes: ``x`` is its edge next to the car."""

    x: float
    y: float
    side: str
    leader: bool


# Label columns start this far out from the body's sides, clear of a wheel
# marker at its largest (it reaches 0.8 mm past the body).
_LABEL_PAD_MM = 1.5
# A leader that passes this close to another marker reads as pointing at it.
_LEADER_CLEARANCE_MM = 0.4
# A leader stops this short of its label's text.
_LEADER_GAP_MM = 0.6


def _stack(desired: Sequence[float], pitch: float, low: float, high: float) -> list[float]:
    """Centres as close to the sorted *desired* ones as allowed with *pitch* between them."""
    ys: list[float] = []
    for want in desired:
        ys.append(max(want, low, ys[-1] + pitch if ys else low))
    if ys and ys[-1] > high:
        ys[-1] = high
        for index in range(len(ys) - 2, -1, -1):
            ys[index] = min(ys[index], ys[index + 1] - pitch)
    return ys


def _crosses(
    start: tuple[float, float], end: tuple[float, float], circle: tuple[float, float, float]
) -> bool:
    """Whether the segment *start*-*end* passes within the clearance of *circle*."""
    (x0, y0), (x1, y1), (cx, cy, r) = start, end, circle
    dx, dy = x1 - x0, y1 - y0
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((cx - x0) * dx + (cy - y0) * dy) / length2))
    px, py = x0 + t * dx - cx, y0 + t * dy - cy
    return px * px + py * py < (r + _LEADER_CLEARANCE_MM) ** 2


def _segments_cross(
    a: tuple[tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    def turn(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    (p1, p2), (p3, p4) = a, b
    return (turn(p3, p4, p1) * turn(p3, p4, p2) < 0) and (turn(p1, p2, p3) * turn(p1, p2, p4) < 0)


# How far (in label rows) a centre-line marker's label may move up or down to
# find a leader that passes no other marker.
_LABEL_SEARCH_ROWS = 6


def _diagram_labels(
    circles: dict[str, tuple[float, float, float]],
    *,
    body_x0: float,
    body_x1: float,
    pitch: float,
    low: float,
    high: float,
) -> dict[str, _DiagramLabel]:
    """Place each marker's label in a column beside the car, so no two overlap.

    *circles* maps a location code to its marker ``(cx, cy, r)`` in millimetres,
    y down. A marker on the left or right half gets its label on that side, at
    its own height when that is free. A marker on the centre line gets its label
    on the side, and as close to its own height, where its leader passes no
    other marker and crosses no other leader (else the fewest), then on the side
    with fewer labels. Labels stack top to bottom at least *pitch* apart. The
    app's diagram places its labels the same way (``ownerDiagram`` in
    apps/ui/src/pages/history/history_model.ts).
    """
    edge = {"left": body_x0 - _LABEL_PAD_MM, "right": body_x1 + _LABEL_PAD_MM}
    mid = (body_x0 + body_x1) / 2
    columns: dict[str, list[str]] = {"left": [], "right": []}
    wanted = {code: cy for code, (_cx, cy, _r) in circles.items()}
    centre: list[str] = []
    for code, (cx, _cy, _r) in circles.items():
        if abs(cx - mid) < 0.01:
            centre.append(code)
        else:
            columns["left" if cx < mid else "right"].append(code)

    def place(side: str, codes: list[str]) -> dict[str, _DiagramLabel]:
        ordered = sorted(codes, key=lambda code: (wanted[code], code))
        ys = _stack([wanted[code] for code in ordered], pitch, low, high)
        return {
            code: _DiagramLabel(
                x=edge[side],
                y=y,
                side=side,
                leader=not code.endswith("_wheel") or abs(y - circles[code][1]) > 0.3,
            )
            for code, y in zip(ordered, ys, strict=True)
        }

    def clashes(labels: dict[str, _DiagramLabel]) -> int:
        leaders = {
            code: (circles[code][:2], (label.x, label.y))
            for code, label in labels.items()
            if label.leader
        }
        passes = sum(
            _crosses(*leader, circles[other])
            for code, leader in leaders.items()
            for other in circles
            if other != code
        )
        segments = list(leaders.values())
        crossings = sum(
            _segments_cross(a, b) for index, a in enumerate(segments) for b in segments[index + 1 :]
        )
        return passes + crossings

    for code in sorted(centre, key=lambda code: (circles[code][1], code)):
        cy = circles[code][1]
        options = []
        for side in ("left", "right"):
            for rows in range(-_LABEL_SEARCH_ROWS, _LABEL_SEARCH_ROWS + 1):
                wanted[code] = cy + rows * pitch
                cost = clashes(place(side, [*columns[side], code]))
                options.append((cost, abs(rows), len(columns[side]), side, wanted[code]))
        _cost, _rows, _count, side, wanted[code] = min(options)
        columns[side].append(code)
    return {**place("left", columns["left"]), **place("right", columns["right"])}


def _car_diagram(
    canvas: Canvas, diagram: CarDiagram, x: float, y_top: float, width: float, height: float
) -> None:
    _box(canvas, x, y_top, width, height, fill=SURFACE)
    body_w = width * 0.52
    body_h = height - 18 * MM
    bx = x + (width - body_w) / 2
    by_top = y_top - 9 * MM

    def point(nx: float, ny: float) -> tuple[float, float]:
        return bx + nx * body_w, by_top - ny * body_h

    canvas.setFont(BOLD, 7)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(x + width / 2, y_top - 5.5 * MM, diagram.front_label)
    zone = diagram.zone
    canvas.setStrokeColor(MUTED)
    canvas.setLineWidth(1)
    canvas.setFillColor(colors.white)
    canvas.roundRect(bx, by_top - body_h, body_w, body_h, body_w * 0.28, stroke=1, fill=1)
    # Windscreen and rear window.
    canvas.setFillColor(GREY_SOFT)
    wx0, wy0 = point(0.18, 0.30)
    wx1, wy1 = point(0.82, 0.37)
    canvas.roundRect(wx0, wy1, wx1 - wx0, wy0 - wy1, 1.5 * MM, stroke=0, fill=1)
    rx0, ry0 = point(0.2, 0.74)
    rx1, ry1 = point(0.8, 0.79)
    canvas.roundRect(rx0, ry1, rx1 - rx0, ry0 - ry1, 1.5 * MM, stroke=0, fill=1)
    if zone in _ZONE_RECTS:
        x0, y0, x1, y1 = _ZONE_RECTS[zone]
        (px0, py0), (px1, py1) = point(x0, y0), point(x1, y1)
        canvas.setFillColor(BRAND_SOFT)
        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(1)
        canvas.roundRect(px0, py1, px1 - px0, py0 - py1, 2 * MM, stroke=1, fill=1)
    highlighted_wheels = {
        "front_axle": {"front_left_wheel", "front_right_wheel"},
        "rear_axle": {"rear_left_wheel", "rear_right_wheel"},
        "all_wheels": set(_WHEEL_CODES),
    }.get(zone or "", {zone})
    for code in _WHEEL_CODES:
        cx, cy = point(*_POSITIONS[code])
        canvas.setFillColor(BRAND if code in highlighted_wheels else colors.HexColor("#3a3d46"))
        canvas.roundRect(cx - 2.2 * MM, cy - 5 * MM, 4.4 * MM, 10 * MM, 1.2 * MM, stroke=0, fill=1)
    markers = {marker.code: marker for marker in diagram.markers if marker.code in _POSITIONS}
    # The label layout works in millimetres from the box's top-left corner, y down.
    circles: dict[str, tuple[float, float, float]] = {}
    for code, marker in markers.items():
        cx, cy = point(*_POSITIONS[code])
        ratio = marker.ratio if marker.ratio is not None else 0.0
        circles[code] = ((cx - x) / MM, (y_top - cy) / MM, 1.6 + 2.4 * max(0.0, min(1.0, ratio)))
    font_size = 7
    labels = _diagram_labels(
        circles,
        body_x0=(bx - x) / MM,
        body_x1=(bx - x + body_w) / MM,
        pitch=font_size * 1.3 / MM,
        low=7.0,
        high=height / MM - 2.0,
    )

    def at(mx: float, my: float) -> tuple[float, float]:
        return x + mx * MM, y_top - my * MM

    canvas.setStrokeColor(MUTED)
    canvas.setLineWidth(0.4)
    for code, label in labels.items():
        if label.leader:
            # Up to just short of the text.
            end_x = label.x + (_LEADER_GAP_MM if label.side == "left" else -_LEADER_GAP_MM)
            canvas.line(*at(*circles[code][:2]), *at(end_x, label.y))
    for code, marker in markers.items():
        cx, cy, r = circles[code]
        canvas.setStrokeColor(colors.white)
        canvas.setLineWidth(1)
        canvas.setFillColor(BRAND if marker.strongest else colors.HexColor("#9aa0ad"))
        canvas.circle(*at(cx, cy), r * MM, stroke=1, fill=1)
    canvas.setFillColor(INK)
    for code, label in labels.items():
        marker = markers[code]
        canvas.setFont(BOLD if marker.strongest else FONT, font_size)
        # The digits' middle sits on the label's centre line.
        tx, ty = at(label.x, label.y)
        draw = canvas.drawRightString if label.side == "left" else canvas.drawString
        draw(tx, ty - font_size * 0.35, marker.value)


# -- page 2 --------------------------------------------------------------------------


def _mechanic_tables(canvas: Canvas, page: MechanicPage) -> float:
    """Title, conditions, worksheet, amplitudes, and ruled-out list; return the y below."""
    y = PAGE_H - MARGIN
    canvas.setFont(BOLD, 13)
    canvas.setFillColor(BRAND)
    canvas.drawString(MARGIN, y - 5 * MM, page.title)
    y -= 11 * MM
    y = _section_title(canvas, page.conditions_title, MARGIN, y)
    y = _facts_grid(canvas, page.conditions, MARGIN, y, CONTENT_W, columns=4, value_size=8) - 1 * MM

    y = _section_title(canvas, page.worksheet_title, MARGIN, y - 1 * MM)
    if page.worksheet:
        widths = (0.24, 0.15, 0.13, 0.17, 0.08, 0.13, 0.10)
        y = _table(
            canvas,
            page.worksheet_header,
            [
                (
                    row.order,
                    row.frequency,
                    row.speeds,
                    row.phases,
                    row.present,
                    row.location,
                    row.level,
                )
                for row in page.worksheet
            ],
            MARGIN,
            y,
            [_Column(CONTENT_W * w, bold=i == 0) for i, w in enumerate(widths)],
            size=7.5,
            highlight=[row.diagnosed for row in page.worksheet],
        )
    if page.worksheet_empty:
        y = _paragraph(canvas, page.worksheet_empty, MARGIN, y - 1 * MM, CONTENT_W, size=8.5)
    y -= GAP + 5 * MM

    half = (CONTENT_W - GAP) / 2
    top = y
    left_y = _section_title(canvas, page.amplitude_title, MARGIN, top)
    left_y = _table(
        canvas,
        page.amplitude_header,
        [(row.location, row.amplitude, row.ratio) for row in page.amplitudes],
        MARGIN,
        left_y,
        [_Column(half * 0.40), _Column(half * 0.38), _Column(half * 0.22)],
        size=7.5,
        highlight=[row.strongest for row in page.amplitudes],
    )
    right_x = MARGIN + half + GAP
    right_y = _section_title(canvas, page.ruled_out_title, right_x, top)
    for line in page.ruled_out:
        right_y = _paragraph(canvas, line, right_x, right_y, half, size=8) - 1 * MM
    y = min(left_y, right_y) - GAP
    return y


def _shop_height(page: MechanicPage) -> float:
    inner = CONTENT_W - 8 * MM
    return 9 * MM + sum(
        _paragraph_height(line, inner - 4 * MM, size=8.5) + 1 * MM for line in page.shop
    )


def _chart_room(page: MechanicPage, y: float) -> float:
    return y - _shop_height(page) - 2 * GAP - _CONTENT_BOTTOM


def _charts_fit_on_workshop_page(page: MechanicPage) -> bool:
    """Lay the page-2 tables out on a scratch canvas to see whether the charts still fit."""
    if page.spectrum is None and page.speed_chart is None:
        return True
    y = _mechanic_tables(Canvas(BytesIO(), pagesize=A4), page)
    return _chart_room(page, y) >= _CHART_MIN_H


def _mechanic_page(canvas: Canvas, page: MechanicPage, *, with_charts: bool) -> None:
    y = _mechanic_tables(canvas, page)
    if with_charts:
        y = _charts(canvas, page, y, min(_CHART_H, _chart_room(page, y)))
    _shop_box(canvas, page, y)


def _charts(canvas: Canvas, page: MechanicPage, y: float, chart_h: float) -> float:
    """Spectrum and amplitude-vs-speed side by side (or one full width); return the y below."""
    half = (CONTENT_W - GAP) / 2
    if page.spectrum and page.speed_chart:
        _spectrum_chart(canvas, page.spectrum, MARGIN, y, half, chart_h)
        _speed_chart(canvas, page.speed_chart, MARGIN + half + GAP, y, half, chart_h)
    elif page.spectrum:
        _spectrum_chart(canvas, page.spectrum, MARGIN, y, CONTENT_W, chart_h)
    elif page.speed_chart:
        _speed_chart(canvas, page.speed_chart, MARGIN, y, CONTENT_W, chart_h)
    else:
        return y
    return y - chart_h - GAP


def _shop_box(canvas: Canvas, page: MechanicPage, y: float) -> None:
    inner = CONTENT_W - 8 * MM
    _box(canvas, MARGIN, y, CONTENT_W, _shop_height(page), fill=SURFACE, stroke=LINE)
    canvas.setFont(BOLD, 10)
    canvas.setFillColor(INK)
    canvas.drawString(MARGIN + 4 * MM, y - 6 * MM, page.shop_title)
    ty = y - 11 * MM
    for line in page.shop:
        canvas.setFillColor(BRAND)
        canvas.circle(MARGIN + 5 * MM, ty + 1.1 * MM, 0.7 * MM, stroke=0, fill=1)
        ty = _paragraph(canvas, line, MARGIN + 8 * MM, ty, inner - 4 * MM, size=8.5) - 1 * MM


# -- charts --------------------------------------------------------------------------


def _nice_step(span: float, target_ticks: int) -> float:
    raw = span / max(1, target_ticks)
    magnitude = 10 ** floor(log10(raw)) if raw > 0 else 1.0
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def _axes(
    canvas: Canvas,
    title: str,
    x: float,
    y_top: float,
    width: float,
    height: float,
    x_range: tuple[float, float],
    y_max: float,
    x_unit: str,
    y_unit: str,
    top_pad: float = 0.0,
) -> tuple[float, float, float, float]:
    """Draw title, frame, ticks; return the plot area (left, bottom, width, height)."""
    canvas.setFont(BOLD, 8.5)
    canvas.setFillColor(INK)
    canvas.drawString(x, y_top - 3 * MM, title)
    left, bottom = x + 11 * MM, y_top - height + 8 * MM
    plot_w, plot_h = width - 13 * MM, height - 15 * MM - top_pad
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.rect(left, bottom, plot_w, plot_h, stroke=1, fill=0)
    canvas.setFont(FONT, 6.5)
    canvas.setFillColor(MUTED)
    x0, x1 = x_range
    step = _nice_step(x1 - x0, 6)
    tick = ceil(x0 / step) * step
    while tick <= x1 + 1e-9:
        px = left + (tick - x0) / (x1 - x0) * plot_w
        canvas.line(px, bottom, px, bottom - 1 * MM)
        canvas.drawCentredString(px, bottom - 3.5 * MM, f"{tick:g}")
        tick += step
    canvas.drawRightString(left + plot_w, bottom - 6.5 * MM, x_unit)
    ystep = _nice_step(y_max, 4)
    tick = 0.0
    while tick <= y_max + 1e-9:
        py = bottom + tick / y_max * plot_h
        canvas.setStrokeColor(GREY_SOFT)
        canvas.line(left, py, left + plot_w, py)
        canvas.drawRightString(left - 1.2 * MM, py - 2, f"{tick:g}")
        tick += ystep
    canvas.saveState()
    canvas.translate(x + 2.5 * MM, bottom + plot_h / 2)
    canvas.rotate(90)
    canvas.drawCentredString(0, 0, y_unit)
    canvas.restoreState()
    return left, bottom, plot_w, plot_h


def _spectrum_chart(
    canvas: Canvas, chart: SpectrumChart, x: float, y_top: float, width: float, height: float
) -> None:
    peak_max = max(amplitude for _hz, amplitude in chart.peaks)
    y_max = max(peak_max, chart.floor_mg or 0.0) * 1.18
    ystep = _nice_step(y_max, 4)
    y_max = ceil(y_max / ystep) * ystep
    # Room above the plot for a second row of marker labels.
    left, bottom, plot_w, plot_h = _axes(
        canvas,
        chart.title,
        x,
        y_top,
        width,
        height,
        (0.0, chart.x_max_hz),
        y_max,
        "Hz",
        "mg",
        top_pad=2.4 * MM,
    )

    def px(hz: float) -> float:
        return left + hz / chart.x_max_hz * plot_w

    def py(amplitude: float) -> float:
        return bottom + min(amplitude, y_max) / y_max * plot_h

    # Orders a few hertz apart (a six's E3 next to P2) would print their labels
    # over each other: a label that would touch the one before goes a line up.
    row_ends = [-inf, -inf]
    for marker in chart.markers:
        if marker.hz > chart.x_max_hz:
            continue
        diagnosed = marker.code == chart.highlight
        canvas.setStrokeColor(BRAND if diagnosed else MUTED)
        canvas.setLineWidth(0.8 if diagnosed else 0.4)
        canvas.setDash(2, 2)
        canvas.line(px(marker.hz), bottom, px(marker.hz), bottom + plot_h)
        canvas.setDash()
        font = BOLD if diagnosed else FONT
        half = canvas.stringWidth(marker.label, font, 6.5) / 2
        row = next((row for row, end in enumerate(row_ends) if px(marker.hz) - half > end), 0)
        row_ends[row] = px(marker.hz) + half + 0.8 * MM
        canvas.setFont(font, 6.5)
        canvas.setFillColor(BRAND if diagnosed else MUTED)
        canvas.drawCentredString(
            px(marker.hz), bottom + plot_h + (1.2 + 2.4 * row) * MM, marker.label
        )
    if chart.floor_mg is not None:
        canvas.setStrokeColor(GOOD)
        canvas.setLineWidth(0.6)
        canvas.setDash(4, 2)
        canvas.line(left, py(chart.floor_mg), left + plot_w, py(chart.floor_mg))
        canvas.setDash()
        canvas.setFont(FONT, 6)
        canvas.setFillColor(GOOD)
        canvas.drawString(left + 1 * MM, py(chart.floor_mg) + 1 * MM, chart.floor_label)
    canvas.setStrokeColor(INK)
    canvas.setFillColor(INK)
    canvas.setLineWidth(1.1)
    for hz, amplitude in chart.peaks:
        if hz > chart.x_max_hz:
            continue
        canvas.line(px(hz), bottom, px(hz), py(amplitude))
        canvas.circle(px(hz), py(amplitude), 0.55 * MM, stroke=0, fill=1)


def _speed_chart(
    canvas: Canvas, chart: SpeedChart, x: float, y_top: float, width: float, height: float
) -> None:
    speeds = [speed for series in chart.series for speed, _amp in series.points]
    amplitudes = [amp for series in chart.series for _speed, amp in series.points]
    x0, x1 = floor(min(speeds) / 10) * 10, ceil(max(speeds) / 10) * 10
    y_max = max(amplitudes) * 1.18
    ystep = _nice_step(y_max, 4)
    y_max = ceil(y_max / ystep) * ystep
    legend_h = 7 * MM
    left, bottom, plot_w, plot_h = _axes(
        canvas,
        chart.title,
        x,
        y_top,
        width,
        height,
        (x0, x1),
        y_max,
        chart.speed_unit,
        "mg",
        top_pad=legend_h,
    )
    legend_x = left
    legend_y = y_top - 3 * MM - legend_h
    for index, series in reversed(list(enumerate(chart.series))):
        color = SERIES[min(index, len(SERIES) - 1)]
        canvas.setStrokeColor(color)
        canvas.setLineWidth(1.6 if series.strongest else 0.9)
        path = canvas.beginPath()
        for point_index, (speed, amplitude) in enumerate(series.points):
            pxv = left + (speed - x0) / (x1 - x0) * plot_w
            pyv = bottom + amplitude / y_max * plot_h
            if point_index == 0:
                path.moveTo(pxv, pyv)
            else:
                path.lineTo(pxv, pyv)
        canvas.drawPath(path, stroke=1, fill=0)
    canvas.setFont(FONT, 6.5)
    lx, ly = legend_x, legend_y
    for index, series in enumerate(chart.series):
        entry_w = 7 * MM + canvas.stringWidth(series.label, FONT, 6.5)
        if lx + entry_w > left + plot_w and lx > legend_x:
            lx, ly = legend_x, ly - 3 * MM
        color = SERIES[min(index, len(SERIES) - 1)]
        canvas.setStrokeColor(color)
        canvas.setLineWidth(1.6 if series.strongest else 0.9)
        canvas.line(lx, ly + 0.8 * MM, lx + 4 * MM, ly + 0.8 * MM)
        canvas.setFillColor(INK)
        canvas.drawString(lx + 5 * MM, ly, series.label)
        lx += entry_w


# -- page 3 --------------------------------------------------------------------------


def _quality_section(canvas: Canvas, quality: QualitySection, y: float) -> None:
    canvas.setFont(BOLD, 13)
    canvas.setFillColor(BRAND)
    canvas.drawString(MARGIN, y - 5 * MM, quality.title)
    y -= 12 * MM
    if quality.checks:
        y = (
            _table(
                canvas,
                quality.header,
                [(check.label, check.state, check.detail) for check in quality.checks],
                MARGIN,
                y,
                [
                    _Column(CONTENT_W * 0.28, bold=True),
                    _Column(CONTENT_W * 0.10),
                    _Column(CONTENT_W * 0.62),
                ],
                size=8,
                highlight=[not check.passed for check in quality.checks],
            )
            - GAP
            - 2 * MM
        )
    for warning in quality.warnings:
        canvas.setFillColor(WARN)
        canvas.circle(MARGIN + 1.2 * MM, y + 1.1 * MM, 0.8 * MM, stroke=0, fill=1)
        y = _paragraph(canvas, warning, MARGIN + 4 * MM, y, CONTENT_W - 4 * MM, size=9) - 1.5 * MM
    y -= GAP
    _facts_grid(canvas, quality.traceability, MARGIN, y, CONTENT_W, columns=2)
