"""Action preview rendering for report page 1."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.action_cards import (
    draw_compact_action_card,
    estimate_compact_action_card_height,
)
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_SMALL,
    PANEL_HEADER_H,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text, _measure_text_height

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import Page1RenderPlan

__all__ = ["draw_actions_block", "estimate_actions_block_height"]

ACTION_PANEL_TITLE_SIZE = 12.5
BRIEF_LABEL_SIZE = 7.0
BRIEF_VALUE_SIZE = 8.4
EVIDENCE_TIMELINE_TITLE_SIZE = 7.2
EVIDENCE_TIMELINE_VALUE_SIZE = 6.4


def _primary_action_text(plan: Page1RenderPlan, *, tr: Callable[..., str]) -> str:
    if plan.next_steps:
        return plan.next_steps[0].action
    verdict = plan.verdict_page
    source = str(verdict.suspected_source or "").strip()
    location = str(verdict.inspect_first or "").strip()
    if source and location:
        return tr("REPORT_PAGE1_DERIVED_ACTION", source=source, location=location)
    return tr("NO_NEXT_STEPS")


def _primary_action_reason(plan: Page1RenderPlan) -> str | None:
    if plan.next_steps and plan.next_steps[0].why:
        why = str(plan.next_steps[0].why).strip()
        reason = str(plan.verdict_page.reason_sentence or "").strip()
        if why and why != reason:
            return why
    return None


def _check_result_rows(
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    confirm: str | None,
    falsify: str | None,
) -> list[tuple[str, str]]:
    verdict = plan.verdict_page
    needs_recapture = (
        verdict.action_status == tr("REPORT_ACTION_STATUS_RECAPTURE")
        or not str(verdict.inspect_first or "").strip()
    )
    confirm_text = str(confirm or "").strip() or tr(
        "REPORT_PAGE1_CONFIRM_RECAPTURE_GENERIC"
        if needs_recapture
        else "REPORT_PAGE1_CONFIRM_GENERIC"
    )
    fallback = str(verdict.fallback_path or "").strip()
    falsify_text = str(falsify or "").strip()
    if not falsify_text:
        falsify_text = (
            tr("REPORT_PAGE1_FALSIFY_FALLBACK_GENERIC")
            if fallback
            else tr("REPORT_PAGE1_FALSIFY_RECAPTURE_GENERIC")
        )
    return [
        (tr("CONFIRM"), confirm_text),
        (tr("REPORT_FALSIFY_COLUMN"), falsify_text),
        (
            tr("REPORT_PAGE1_PARTS_GATE_LABEL"),
            tr(
                "REPORT_PAGE1_PARTS_GATE_RECAPTURE_GENERIC"
                if needs_recapture
                else "REPORT_PAGE1_PARTS_GATE_GENERIC"
            ),
        ),
    ]


def estimate_actions_block_height(
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    w: float,
) -> float:
    """Estimate the page-1 action preview panel height."""

    content_w = w - 8 * mm
    content_h = 0.0
    content_h += estimate_compact_action_card_height(
        title=_primary_action_text(plan, tr=tr),
        why=_primary_action_reason(plan),
        width=content_w,
        show_badge=False,
    )
    content_h += 78 * mm
    if plan.verdict_page.timeline_graph is not None:
        content_h += 24 * mm
    return float(max(30 * mm, PANEL_HEADER_H + 2 * mm + content_h + 4 * mm))


def draw_actions_block(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    """Draw the page-1 action preview panel."""

    _draw_panel(c, x, y, w, h)
    inner_x = x + 4 * mm
    content_w = w - 8 * mm
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, ACTION_PANEL_TITLE_SIZE)
    c.drawString(inner_x, y + h - 6.2 * mm, tr("REPORT_ACTIONS_PANEL_TITLE"))

    row_y = draw_compact_action_card(
        c,
        index=None,
        title=_primary_action_text(plan, tr=tr),
        why=_primary_action_reason(plan),
        x=inner_x,
        y_top=y + h - 15.5 * mm,
        w=content_w,
    )

    first_step = plan.next_steps[0] if plan.next_steps else None
    check_bottom_y = _draw_check_result_block(
        c,
        plan,
        tr=tr,
        confirm=first_step.confirm if first_step is not None else None,
        falsify=first_step.falsify if first_step is not None else None,
        x=inner_x,
        y_bottom=y + 5 * mm,
        y_top=row_y,
        w=content_w,
    )
    _draw_evidence_timeline_strip(
        c,
        plan,
        tr=tr,
        x=inner_x,
        y_bottom=y + 5 * mm,
        y_top=check_bottom_y - 1.0 * mm,
        w=content_w,
    )


def _draw_check_result_block(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    confirm: str | None,
    falsify: str | None,
    x: float,
    y_bottom: float,
    y_top: float,
    w: float,
) -> float:
    rows = _check_result_rows(plan, tr=tr, confirm=confirm, falsify=falsify)
    if not rows:
        return y_top

    row_gap = 1.5 * mm
    row_heights = [
        max(
            20 * mm,
            min(
                28 * mm,
                _measure_text_height(
                    value,
                    w=w - 6 * mm,
                    size=BRIEF_VALUE_SIZE,
                    leading=BRIEF_VALUE_SIZE + 1.0,
                    max_lines=3,
                )
                + (12 * mm),
            ),
        )
        for _, value in rows
    ]
    available_h = y_top - y_bottom
    min_needed = 16 * mm + sum(row_heights) + ((len(rows) - 1) * row_gap)
    if available_h < min_needed:
        return y_bottom

    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(x, y_top - 2.0 * mm, tr("REPORT_PAGE1_CHECK_RESULT_TITLE"))
    row_area_top = y_top - 7.5 * mm
    row_y = row_area_top
    row_styles = (
        (REPORT_COLORS["card_success_bg"], REPORT_COLORS["card_success_border"]),
        (REPORT_COLORS["surface"], REPORT_COLORS["table_row_border"]),
        (REPORT_COLORS["card_warn_bg"], REPORT_COLORS["card_warn_border"]),
    )
    for index, (label, value) in enumerate(rows):
        row_h = row_heights[index]
        row_y -= row_h
        fill, border = row_styles[min(index, len(row_styles) - 1)]
        c.setFillColor(_hex(fill))
        c.setStrokeColor(_hex(border))
        c.roundRect(x, row_y, w, row_h, 2.4 * mm, stroke=1, fill=1)
        value_h = _measure_text_height(
            value,
            w=w - 6 * mm,
            size=BRIEF_VALUE_SIZE,
            leading=BRIEF_VALUE_SIZE + 1.0,
            max_lines=3,
        )
        content_h = value_h + 8.2 * mm
        top_pad = max(4.0 * mm, (row_h - content_h) / 2.0)
        label_y = row_y + row_h - top_pad
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, BRIEF_LABEL_SIZE)
        c.drawString(x + 3 * mm, label_y, label)
        _draw_text(
            c,
            x + 3 * mm,
            label_y - 4.2 * mm,
            w - 6 * mm,
            value,
            font=FONT_B,
            size=BRIEF_VALUE_SIZE,
            color=TEXT_CLR,
            leading=BRIEF_VALUE_SIZE + 1.0,
            max_lines=3,
        )
        row_y -= row_gap
    return float(row_y)


def _draw_evidence_timeline_strip(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y_bottom: float,
    y_top: float,
    w: float,
) -> None:
    timeline = plan.verdict_page.timeline_graph
    if timeline is None:
        return
    available_h = y_top - y_bottom
    if available_h < 21 * mm:
        return

    h = min(30 * mm, available_h)
    y = y_bottom
    c.setFillColor(_hex(REPORT_COLORS["surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
    c.roundRect(x, y, w, h, 2.4 * mm, stroke=1, fill=1)

    title_y = y + h - 4.0 * mm
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, EVIDENCE_TIMELINE_TITLE_SIZE)
    c.drawString(x + 3 * mm, title_y, tr("REPORT_PAGE1_EVIDENCE_TIMELINE_TITLE"))

    evidence_count = sum(1 for interval in timeline.intervals if interval.has_fault_evidence)
    summary_key = (
        "REPORT_PAGE1_EVIDENCE_TIMELINE_SUMMARY_ONE"
        if evidence_count == 1
        else "REPORT_PAGE1_EVIDENCE_TIMELINE_SUMMARY_MANY"
    )
    summary = tr(summary_key, count=evidence_count)
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, EVIDENCE_TIMELINE_VALUE_SIZE)
    c.drawRightString(x + w - 3 * mm, title_y, summary)

    plot_x = x + 3 * mm
    plot_w = w - 6 * mm
    track_y = y + 8.8 * mm
    track_h = 4.6 * mm
    c.setFillColor(_hex(REPORT_COLORS["surface_alt"]))
    c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
    c.roundRect(plot_x, track_y, plot_w, track_h, 1.5 * mm, stroke=1, fill=1)
    duration_s = max(0.1, float(timeline.duration_s))
    for interval in timeline.intervals:
        start_x = plot_x + (max(0.0, interval.start_t_s) / duration_s * plot_w)
        end_x = plot_x + (min(duration_s, interval.end_t_s) / duration_s * plot_w)
        interval_w = max(1.5, end_x - start_x)
        if interval.has_fault_evidence:
            c.setFillColor(_hex(REPORT_COLORS["brand"]))
            c.roundRect(start_x, track_y, interval_w, track_h, 1.2 * mm, stroke=0, fill=1)
        elif interval.speed_min_kmh is not None or interval.speed_max_kmh is not None:
            c.setFillColor(_hex(REPORT_COLORS["brand_surface"]))
            c.roundRect(start_x, track_y, interval_w, track_h, 1.2 * mm, stroke=0, fill=1)

    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, EVIDENCE_TIMELINE_VALUE_SIZE)
    c.drawString(plot_x, y + 4.0 * mm, "0")
    c.drawRightString(plot_x + plot_w, y + 4.0 * mm, _format_timeline_seconds(duration_s))


def _format_timeline_seconds(seconds: float) -> str:
    rounded = max(0, int(round(seconds)))
    minutes, secs = divmod(rounded, 60)
    if minutes:
        return f"{minutes}:{secs:02d}"
    return f"{secs}s"
