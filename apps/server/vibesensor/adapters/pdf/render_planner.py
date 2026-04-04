"""PDF page-sequencing planner over the canonical report document."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting.document import ReportDocument

from .pdf_appendices.action_matrix import worksheet_step_pages
from .report_types import (
    AppendixAPageRenderPlan,
    AppendixBRenderPlan,
    ReportPdfRenderPlan,
    build_appendix_b_render_plan,
    build_appendix_c_render_plan,
    build_page1_render_plan,
)

__all__ = ["build_report_render_plan"]


def build_report_render_plan(data: ReportDocument) -> ReportPdfRenderPlan:
    """Build the complete adapter-side render plan for the shipped PDF flow."""

    recapture_mode = data.appendix_a.mode == "recapture"
    appendix_a_pages = _appendix_a_page_plans(data)
    appendix_b = _appendix_b_render_plan(data, recapture_mode=recapture_mode)
    total_pages = (
        1 + len(appendix_a_pages)
        if recapture_mode
        else len(appendix_a_pages) + 2 + (1 if appendix_b is not None else 0)
    )
    return ReportPdfRenderPlan(
        document_title=data.title or "VibeSensor Diagnostic Report",
        page1=build_page1_render_plan(data),
        appendix_a_pages=appendix_a_pages,
        appendix_b=appendix_b,
        appendix_c=build_appendix_c_render_plan(data),
        recapture_mode=recapture_mode,
        total_pages=total_pages,
    )


def _appendix_a_page_plans(data: ReportDocument) -> tuple[AppendixAPageRenderPlan, ...]:
    trace_rows = tuple(data.traceability_rows)
    if data.appendix_a.mode == "recapture":
        return (
            AppendixAPageRenderPlan(
                lang=data.lang,
                appendix=data.appendix_a,
                trace_rows=trace_rows,
                steps=(),
                start_number=1,
                continued=False,
            ),
        )

    step_pages = worksheet_step_pages(data.appendix_a, list(data.next_steps), lang=data.lang)
    page_plans: list[AppendixAPageRenderPlan] = []
    start_number = 1
    for index, page_steps in enumerate(step_pages):
        page_plans.append(
            AppendixAPageRenderPlan(
                lang=data.lang,
                appendix=data.appendix_a,
                trace_rows=trace_rows,
                steps=tuple(page_steps),
                start_number=start_number,
                continued=index > 0,
            )
        )
        start_number += len(page_steps)
    return tuple(page_plans)


def _appendix_b_render_plan(
    data: ReportDocument,
    *,
    recapture_mode: bool,
) -> AppendixBRenderPlan | None:
    if recapture_mode:
        return None
    appendix_b = build_appendix_b_render_plan(data)
    if not _has_appendix_b_content(appendix_b):
        return None
    return appendix_b


def _has_appendix_b_content(plan: AppendixBRenderPlan) -> bool:
    appendix = plan.appendix
    return any(
        (
            appendix.dominant_corner,
            appendix.runner_up_corner,
            appendix.dominance_ratio_text,
            appendix.location_confidence,
            appendix.coverage_label,
            appendix.coverage_notes,
            appendix.intensity_rows,
            appendix.sensor_observation_rows,
        )
    )
