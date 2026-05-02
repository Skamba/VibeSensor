"""Proof and timeline rendering for report page 1."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.page1_common import draw_label_value
from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_BODY,
    FS_H2,
    FS_SMALL,
    PANEL_HEADER_H,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text, _truncate_single_line
from vibesensor.adapters.pdf.pdf_timeline_render import run_timeline_graph
from vibesensor.domain import VibrationSource
from vibesensor.shared.report_presentation import human_source

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import Page1RenderPlan

__all__ = ["draw_proof_block", "draw_timeline_block"]

PROOF_PANEL_TITLE_SIZE = 12.5
PROOF_SUMMARY_LABEL_SIZE = 6.4
PROOF_SUMMARY_VALUE_SIZE = 6.8
SOURCE_COMPARE_TITLE_SIZE = 7.4
SOURCE_COMPARE_LABEL_SIZE = 6.8
SOURCE_COMPARE_VALUE_SIZE = 6.6
SOURCE_COMPARE_MISSING_RATIO = 0.08
SOURCE_COMPARE_CORE_SOURCES = (
    VibrationSource.WHEEL_TIRE,
    VibrationSource.DRIVELINE,
    VibrationSource.ENGINE,
)


@dataclass(frozen=True, slots=True)
class _SourceComparisonRow:
    source: str
    confidence: float | None
    missing: bool = False


def draw_proof_block(
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
    _draw_panel(c, x, y, w, h)
    inner_x = x + 4 * mm
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, PROOF_PANEL_TITLE_SIZE)
    c.drawString(
        x + 4 * mm, y + h - 6.2 * mm, verdict.proof_panel_title or tr("REPORT_PROOF_PANEL_TITLE")
    )

    inner_y = y + h - 15.5 * mm
    diagram_w = w * 0.42
    left_x = inner_x
    left_w = diagram_w - 2 * mm
    left_bottom = y + 7 * mm
    left_top = inner_y
    left_content_h = left_top - left_bottom
    diagram_y = left_bottom + (4 * mm)
    diagram_h = left_content_h - (4 * mm)
    diagram = car_location_diagram(
        _page1_diagram_findings(plan),
        {
            "sensor_locations": plan.sensor_locations,
            "sensor_intensity_by_location": plan.proof_sensor_intensity_by_location,
        },
        plan.proof_location_hotspot_rows,
        content_width=w - 8 * mm,
        tr=tr,
        diagram_width=left_w,
        diagram_height=diagram_h - 2 * mm,
        vertical_align="top",
        highlight_fill=True,
    )
    diagram.drawOn(c, left_x, diagram_y)

    text_x = x + diagram_w + 5 * mm
    text_w = w - diagram_w - 9 * mm
    text_y = inner_y
    text_y = draw_label_value(
        c,
        x=text_x,
        y=text_y,
        width=text_w,
        label=tr("REPORT_DOMINANT_CORNER_LABEL"),
        value=verdict.dominant_corner or tr("UNKNOWN"),
        value_size=FS_H2,
    )
    if verdict.runner_up_corner:
        text_y = draw_label_value(
            c,
            x=text_x,
            y=text_y,
            width=text_w,
            label=tr("REPORT_RUNNER_UP_CORNER_LABEL"),
            value=verdict.runner_up_corner,
            value_size=FS_BODY,
        )
    if verdict.dominance_ratio_label:
        text_y = draw_label_value(
            c,
            x=text_x,
            y=text_y,
            width=text_w,
            label=tr("REPORT_DOMINANCE_RATIO_LABEL"),
            value=verdict.dominance_ratio_label,
            value_size=FS_BODY,
        )
    text_y = draw_label_value(
        c,
        x=text_x,
        y=text_y,
        width=text_w,
        label=tr("REPORT_COVERAGE_LABEL"),
        value=verdict.coverage_label or tr("UNKNOWN"),
        value_size=FS_BODY,
        max_lines=3,
    )
    _draw_proof_summary(
        c, plan, tr=tr, x=text_x, y_top=text_y - 1 * mm, y_bottom=y + 51 * mm, w=text_w
    )
    _draw_source_comparison(
        c,
        plan,
        tr=tr,
        x=inner_x,
        y=y + 7 * mm,
        w=w - 8 * mm,
        h=40 * mm,
    )


def _draw_proof_summary(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y_top: float,
    y_bottom: float,
    w: float,
) -> None:
    verdict = plan.verdict_page
    if y_top - y_bottom < 34 * mm:
        return
    c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
    c.line(x, y_top, x + w, y_top)
    cursor_y = y_top - 4.0 * mm
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, PROOF_SUMMARY_VALUE_SIZE)
    c.drawString(x, cursor_y, tr("REPORT_PAGE1_PROOF_SUMMARY_TITLE"))
    cursor_y -= 3.8 * mm
    if verdict.proof_summary:
        cursor_y = _draw_text(
            c,
            x,
            cursor_y,
            w,
            verdict.proof_summary,
            font=FONT,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=4,
        )
        cursor_y -= 2.0 * mm

    for row in verdict.proof_snapshot_rows[:3]:
        if cursor_y < y_bottom + 10 * mm:
            break
        label = str(row.label or "").strip()
        value = _page1_snapshot_value(label=label, value=str(row.value or "").strip())
        if not label or not value:
            continue
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, PROOF_SUMMARY_LABEL_SIZE)
        c.drawString(x, cursor_y, label)
        cursor_y = _draw_text(
            c,
            x,
            cursor_y - 3.2 * mm,
            w,
            value,
            font=FONT_B,
            size=PROOF_SUMMARY_VALUE_SIZE,
            color=TEXT_CLR,
            leading=PROOF_SUMMARY_VALUE_SIZE + 0.9,
            max_lines=2,
        )
        cursor_y -= 1.6 * mm


def _page1_diagram_findings(plan: Page1RenderPlan) -> tuple[dict[str, object], ...]:
    verdict = plan.verdict_page
    dominant_corner = str(verdict.dominant_corner or "").strip()
    if dominant_corner:
        return (
            {
                "strongest_location": dominant_corner,
                "suspected_source": verdict.suspected_source,
            },
        )
    return tuple(
        {
            "strongest_location": finding.strongest_location,
            "suspected_source": finding.suspected_source,
        }
        for finding in (plan.top_causes or plan.findings)
    )


def _draw_source_comparison(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    rows = _source_comparison_rows(plan, tr=tr)
    if not rows:
        return

    c.setFillColor(_hex(REPORT_COLORS["brand_surface_soft"]))
    c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
    c.roundRect(x, y, w, h, 2.8 * mm, stroke=1, fill=1)

    title_y = y + h - 5.0 * mm
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, SOURCE_COMPARE_TITLE_SIZE)
    c.drawString(x + 3 * mm, title_y, tr("REPORT_PAGE1_SOURCE_COMPARISON_TITLE"))

    row_gap = 1.0 * mm
    row_area_top = title_y - 4.1 * mm
    row_area_bottom = y + 3.5 * mm
    row_h = (row_area_top - row_area_bottom - ((len(rows) - 1) * row_gap)) / len(rows)
    label_w = max(28 * mm, w - 28 * mm)
    bar_w = w - 29 * mm
    bar_h = 2.1 * mm
    row_y = row_area_top - row_h
    bar_colors = (
        REPORT_COLORS["brand"],
        REPORT_COLORS["axis"],
        REPORT_COLORS["text_muted"],
        REPORT_COLORS["axis"],
    )
    for index, row in enumerate(rows):
        fill = bar_colors[min(index, len(bar_colors) - 1)]
        if row.missing:
            fill = REPORT_COLORS["axis"]
        label = _truncate_single_line(row.source, label_w, SOURCE_COMPARE_LABEL_SIZE)
        value = _source_comparison_value(row, tr=tr)
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B if index == 0 else FONT, SOURCE_COMPARE_LABEL_SIZE)
        c.drawString(x + 3 * mm, row_y + row_h - 2.8 * mm, label)
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT_B, SOURCE_COMPARE_VALUE_SIZE)
        c.drawRightString(x + w - 3 * mm, row_y + row_h - 2.8 * mm, value)

        bar_x = x + 3 * mm
        bar_y = row_y + 1.0 * mm
        c.setFillColor(_hex(REPORT_COLORS["surface"]))
        c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
        c.roundRect(bar_x, bar_y, bar_w, bar_h, 1.0 * mm, stroke=1, fill=1)
        fill_ratio = _source_comparison_fill_ratio(row)
        c.setFillColor(_hex(fill))
        c.roundRect(bar_x, bar_y, bar_w * fill_ratio, bar_h, 1.0 * mm, stroke=0, fill=1)
        row_y -= row_h + row_gap


def _source_comparison_value(
    row: _SourceComparisonRow,
    *,
    tr: Callable[..., str],
) -> str:
    if row.missing:
        return tr("REPORT_PAGE1_SOURCE_COMPARISON_NOT_INDICATED")
    if row.confidence is None:
        return tr("REPORT_PAGE1_SOURCE_COMPARISON_UNRANKED")
    return f"{round(row.confidence * 100):d}%"


def _source_comparison_fill_ratio(row: _SourceComparisonRow) -> float:
    if row.missing:
        return SOURCE_COMPARE_MISSING_RATIO
    if row.confidence is None:
        return 0.18
    return max(SOURCE_COMPARE_MISSING_RATIO, min(1.0, row.confidence))


def _source_comparison_rows(
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
) -> list[_SourceComparisonRow]:
    ranked: dict[str, float] = {}
    for finding in plan.top_causes or plan.findings:
        source = human_source(finding.suspected_source, tr=tr).strip()
        if not source:
            continue
        confidence = max(0.0, min(1.0, float(finding.effective_confidence or 0.0)))
        ranked[source] = max(confidence, ranked.get(source, 0.0))

    if ranked:
        return _core_source_rows_with_primary_first(plan, ranked, tr=tr)

    source = str(plan.verdict_page.suspected_source or "").strip()
    if source:
        return _core_source_rows_with_primary_first(plan, {source: 0.0}, tr=tr, unranked=True)
    return _core_source_rows_with_primary_first(plan, {}, tr=tr)


def _core_source_rows_with_primary_first(
    plan: Page1RenderPlan,
    ranked: dict[str, float],
    *,
    tr: Callable[..., str],
    unranked: bool = False,
) -> list[_SourceComparisonRow]:
    rows = _core_source_rows(ranked, tr=tr, unranked=unranked)
    primary = str(plan.verdict_page.suspected_source or "").strip()
    if not primary or primary.casefold() == tr("REPORT_INCONCLUSIVE_SOURCE").casefold():
        return _sort_source_comparison_rows(rows)

    primary_key = _source_compare_key(primary)
    primary_row = next(
        (row for row in rows if _source_compare_key(row.source) == primary_key), None
    )
    if primary_row is None:
        return _sort_source_comparison_rows(rows)

    remaining = [row for row in rows if row != primary_row]
    return [primary_row, *_sort_source_comparison_rows(remaining)]


def _core_source_rows(
    ranked: dict[str, float],
    *,
    tr: Callable[..., str],
    unranked: bool,
) -> list[_SourceComparisonRow]:
    ranked_by_key = {
        _source_compare_key(source): confidence for source, confidence in ranked.items()
    }
    rows: list[_SourceComparisonRow] = []
    for source in SOURCE_COMPARE_CORE_SOURCES:
        label = human_source(source, tr=tr)
        key = _source_compare_key(label)
        if key in ranked_by_key:
            rows.append(
                _SourceComparisonRow(
                    source=label,
                    confidence=None if unranked else ranked_by_key[key],
                )
            )
        else:
            rows.append(_SourceComparisonRow(source=label, confidence=None, missing=True))
    return rows


def _sort_source_comparison_rows(
    rows: list[_SourceComparisonRow],
) -> list[_SourceComparisonRow]:
    return sorted(
        rows,
        key=lambda row: (
            row.missing,
            -(row.confidence or 0.0),
            _source_compare_key(row.source),
        ),
    )


def _source_compare_key(source: str) -> str:
    return "".join(ch for ch in source.casefold() if ch.isalnum())


def _page1_snapshot_value(*, label: str, value: str) -> str:
    """Keep page 1 from implying support-window duration is elapsed runtime."""

    if label.casefold() == "support" and " across " in value:
        return value.split(" across ", 1)[0].strip()
    return value


def draw_timeline_block(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    timeline_graph = plan.verdict_page.timeline_graph
    if timeline_graph is None:
        return

    _draw_panel(c, x, y, w, h, tr("REPORT_TIMELINE_TITLE"))
    graph_x = x + 4 * mm
    graph_y = y + 4 * mm
    graph_w = w - 8 * mm
    graph_h = h - PANEL_HEADER_H - 6 * mm
    run_timeline_graph(
        timeline_graph,
        tr=tr,
        graph_width=graph_w,
        graph_height=graph_h,
        show_title=False,
    ).drawOn(c, graph_x, graph_y)
