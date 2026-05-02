"""Table and traceability rendering helpers for report appendices."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_BODY,
    FS_SMALL,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import (
    _draw_text,
    _wrap_lines,
)
from vibesensor.shared.boundaries.reporting.document import (
    ReportLabelValueRow,
)

__all__ = ["_draw_table", "_draw_traceability_row", "_fmt_db", "_fmt_hz", "_fmt_relative_db"]


def _draw_traceability_row(
    c: Canvas, row: ReportLabelValueRow, *, x: float, y: float, w: float
) -> float:
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(x, y, row.label)
    return _draw_text(
        c,
        x,
        y - 3.4 * mm,
        w,
        row.value,
        font=FONT_B,
        size=FS_BODY,
        color=TEXT_CLR,
        leading=FS_BODY + 1.2,
        max_lines=3,
    )


def _fmt_db(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f} dB"


def _fmt_hz(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f} Hz"


def _fmt_relative_db(value: float | None) -> str:
    if value is None:
        return "—"
    clamped = min(0.0, float(value))
    if clamped > -0.05:
        return "0 dB"
    if clamped > -1.0:
        return f"{clamped:.1f} dB"
    return f"{clamped:.0f} dB"


def _draw_table(
    c: Canvas,
    *,
    x: float,
    y: float,
    w: float,
    y_bottom: float,
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[float],
    max_body_lines: int = 2,
    overflow_text_template: str | None = None,
    overflow_singular_text_template: str | None = None,
) -> int:
    total_ratio = sum(col_widths)
    widths = [w * (ratio / total_ratio) for ratio in col_widths]
    header_lines = [
        _wrap_lines(header, width_part - 3 * mm, FS_SMALL)
        for width_part, header in zip(widths, headers, strict=False)
    ]
    header_line_count = max((len(lines) for lines in header_lines), default=1)
    header_leading = FS_SMALL + 1.0
    header_h = max(8 * mm, (header_line_count * header_leading) + 3.5 * mm)
    c.setFillColor(_hex(REPORT_COLORS["surface_alt"]))
    c.setStrokeColor(_hex(REPORT_COLORS["border"]))
    c.rect(x, y - header_h, w, header_h, stroke=1, fill=1)
    cursor_x = x
    for width_part, lines in zip(widths, header_lines, strict=False):
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_SMALL)
        line_y = y - 3.2 * mm
        for line in lines[:2]:
            c.drawString(cursor_x + 1.5 * mm, line_y, line)
            line_y -= header_leading
        cursor_x += width_part
    current_y = y - header_h
    rendered_count = 0
    for row_index, row in enumerate(rows):
        line_counts = []
        for cell, width_part in zip(row, widths, strict=False):
            line_counts.append(max(1, len(_wrap_lines(str(cell), width_part - 3 * mm, FS_SMALL))))
        row_h = max(9 * mm, min(max_body_lines, max(line_counts)) * (FS_SMALL + 1.2) + 3.5 * mm)
        remaining_after_current = len(rows) - row_index - 1
        if remaining_after_current > 0 and current_y - row_h - (3 * mm) < y_bottom:
            _draw_table_overflow_note(
                c,
                x=x,
                y_top=current_y,
                y_bottom=y_bottom,
                omitted_count=len(rows) - row_index,
                template=overflow_text_template,
                singular_template=overflow_singular_text_template,
            )
            return rendered_count
        if current_y - row_h < y_bottom:
            _draw_table_overflow_note(
                c,
                x=x,
                y_top=current_y,
                y_bottom=y_bottom,
                omitted_count=len(rows) - row_index,
                template=overflow_text_template,
                singular_template=overflow_singular_text_template,
            )
            return rendered_count
        fill = "#ffffff" if row_index % 2 == 0 else REPORT_COLORS["surface"]
        c.setFillColor(_hex(fill))
        c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
        c.rect(x, current_y - row_h, w, row_h, stroke=1, fill=1)
        cursor_x = x
        for cell, width_part in zip(row, widths, strict=False):
            _draw_text(
                c,
                cursor_x + 1.5 * mm,
                current_y - 3.0 * mm,
                width_part - 3 * mm,
                str(cell),
                size=FS_SMALL,
                color=TEXT_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=max_body_lines,
            )
            cursor_x += width_part
        current_y -= row_h
        rendered_count += 1
    return rendered_count


def _draw_table_overflow_note(
    c: Canvas,
    *,
    x: float,
    y_top: float,
    y_bottom: float,
    omitted_count: int,
    template: str | None,
    singular_template: str | None,
) -> None:
    if omitted_count <= 0 or y_top - y_bottom < 3.0 * mm:
        return
    selected_template = (
        singular_template if omitted_count == 1 and singular_template is not None else template
    )
    if selected_template is None:
        selected_template = (
            "+ {count} more row not shown"
            if omitted_count == 1
            else "+ {count} more rows not shown"
        )
    note = selected_template.format(count=omitted_count)
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(x + 1.5 * mm, max(y_bottom + 1.1 * mm, y_top - 2.4 * mm), note)
