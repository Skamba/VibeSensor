"""Page 2 composition for the evidence and diagnostics PDF page."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.panels._panel_diagram import _draw_car_visual_panel
from vibesensor.adapters.pdf.panels._panel_evidence import _draw_pattern_evidence
from vibesensor.adapters.pdf.panels._panel_observations import _draw_additional_observations
from vibesensor.adapters.pdf.panels._panel_peaks import _draw_peaks_table
from vibesensor.adapters.pdf.panels._panel_title_bar import _draw_title_bar
from vibesensor.adapters.pdf.panels._panel_trust_steps import _draw_continued_next_steps
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import (
    GAP,
    PdfRenderContext,
    build_page2_layout,
)
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.document import NextStep, ReportTemplateData


def _page2(
    c: Canvas,
    data: ReportTemplateData,
    *,
    ctx: PdfRenderContext | None = None,
    next_steps_continued: list[NextStep] | None = None,
) -> None:
    """Render page 2: car visual, pattern evidence, and peaks table."""
    render_ctx = ctx or PdfRenderContext.from_data(data)
    width = render_ctx.width
    page_top = render_ctx.page_top

    def tr(key: str) -> str:
        return _tr(data.lang, key)

    transient_findings = [
        finding
        for finding in data.findings
        if finding.severity == "info"
        and (
            str(finding.suspected_source) == "transient_impact"
            or finding.peak_classification == "transient"
        )
    ]
    layout = build_page2_layout(
        width=width,
        page_top=page_top,
        has_transient_findings=bool(transient_findings),
        has_next_steps_continued=bool(next_steps_continued),
    )

    _draw_title_bar(c, title=tr("EVIDENCE_DIAGNOSTICS"), width=width, page_top=page_top)
    _draw_car_visual_panel(
        c,
        data,
        tr_fn=render_ctx.tr_fn,
        text_fn=render_ctx.text_fn,
        x=layout.car_panel.panel.x,
        y=layout.car_panel.panel.y,
        w=layout.car_panel.panel.w,
        h=layout.car_panel.panel.h,
        location_rows=render_ctx.location_rows,
        top_causes=render_ctx.top_causes,
        content_width=width,
    )
    _draw_pattern_evidence(
        c,
        layout.pattern_panel.x,
        layout.pattern_panel.y,
        layout.pattern_panel.w,
        layout.pattern_panel.h,
        data.pattern_evidence,
        tr,
    )
    _draw_panel(
        c,
        layout.peaks_panel.x,
        layout.peaks_panel.y,
        layout.peaks_panel.w,
        layout.peaks_panel.h,
        tr("DIAGNOSTIC_PEAKS"),
    )
    _draw_peaks_table(
        c,
        layout.peaks_panel.x + 4 * mm,
        layout.peaks_panel.y + layout.peaks_panel.h - 10 * mm,
        layout.peaks_panel.w - 8 * mm,
        layout.peaks_panel.y + 3 * mm,
        data,
        tr,
    )

    obs_y = layout.peaks_panel.y
    if layout.observations_panel is not None:
        _draw_additional_observations(
            c,
            layout.observations_panel.x,
            layout.observations_panel.y,
            layout.observations_panel.w,
            layout.observations_panel.h,
            transient_findings,
            tr,
        )
        obs_y = layout.observations_panel.y

    if next_steps_continued:
        page1_drawn = len(data.next_steps) - len(next_steps_continued)
        _draw_continued_next_steps(
            c,
            y_top=obs_y - GAP,
            next_steps_continued=next_steps_continued,
            start_number=page1_drawn + 1,
            tr=tr,
        )
