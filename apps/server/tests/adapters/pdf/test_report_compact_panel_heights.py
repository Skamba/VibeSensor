from __future__ import annotations

from reportlab.lib.units import mm

from vibesensor.adapters.pdf.pdf_appendices import (
    _estimate_appendix_c_context_panel_height,
    _estimate_appendix_c_suitability_panel_height,
    _estimate_appendix_c_trace_panel_height,
    _estimate_worksheet_ranked_stack_height,
    _estimate_worksheet_top_panel_height,
)
from vibesensor.adapters.pdf.pdf_page1 import _estimate_actions_block_height
from vibesensor.adapters.pdf.pdf_style import GAP, MARGIN, PAGE_H, PANEL_HEADER_H
from vibesensor.adapters.pdf.report_data import (
    AppendixAData,
    AppendixCData,
    AppendixDData,
    DataTrustItem,
    NextStep,
    RankedCandidateRow,
    ReportLabelValueRow,
    ReportTemplateData,
)
from vibesensor.adapters.pdf.report_data import VerdictPageData
from vibesensor.report_i18n import tr as i18n_tr


def _tr(key: str, **kwargs: object) -> str:
    return i18n_tr("en", key, **kwargs)


def test_estimate_actions_block_height_shrinks_for_short_content() -> None:
    data = ReportTemplateData(
        lang="en",
        verdict_page=VerdictPageData(),
        next_steps=[
            NextStep(action="Check wheel balance", why="Short reason"),
        ],
    )
    page_top = PAGE_H - MARGIN
    content_bottom = MARGIN + 8 * mm
    main_h = page_top - content_bottom - (26 * mm) - (40 * mm) - (2 * GAP)
    actions_h = _estimate_actions_block_height(data, tr=_tr, w=78 * mm)

    assert actions_h < main_h
    assert actions_h >= PANEL_HEADER_H


def test_estimate_appendix_c_lower_panels_shrink_for_short_content() -> None:
    data = ReportTemplateData(
        lang="en",
        verdict_page=VerdictPageData(action_status_note="skip duplicate"),
        appendix_c=AppendixCData(
            context_summary="Short context note.",
            speed_band_summary="100-110 km/h.",
            phase_summary="Cruise only.",
            observations=["Single repeatable observation."],
            limits_summary="Run quality was acceptable.",
            suitability_items=[
                DataTrustItem(check="Frame integrity", detail="Passed cleanly.", state="pass"),
                DataTrustItem(check="Speed stability", detail="Within expected range.", state="pass"),
            ],
        ),
        appendix_d=AppendixDData(
            rows=[ReportLabelValueRow(label="Evidence", value="One short traceability note.")],
        ),
    )

    context_h = _estimate_appendix_c_context_panel_height(data, width=44 * mm)
    suitability_h = _estimate_appendix_c_suitability_panel_height(data, width=56 * mm)
    trace_h = _estimate_appendix_c_trace_panel_height(data, width=72 * mm)

    assert max(context_h, suitability_h, trace_h) < 90 * mm
    assert min(context_h, suitability_h, trace_h) >= 34 * mm


def test_estimate_worksheet_summary_panels_shrink_for_short_content() -> None:
    appendix = AppendixAData(
        primary_source="Wheel / Tire",
        alternative_source="Driveline",
        why_primary_first="Short reason.",
        why_alternative_next="Backup reason.",
        next_if_clean="Move to the alternative path.",
        ranked_candidates=[
            RankedCandidateRow(source_name="Wheel / Tire", inspect_first="Front-left wheel", path_role="Primary"),
            RankedCandidateRow(source_name="Driveline", inspect_first="Propshaft", path_role="Alternative"),
            RankedCandidateRow(source_name="Engine", inspect_first="Accessory drive", path_role="Third"),
        ],
    )

    top_h = _estimate_worksheet_top_panel_height(appendix, lang="en")
    stack_h = _estimate_worksheet_ranked_stack_height(appendix, lang="en")

    assert top_h < 56 * mm
    assert stack_h <= 48 * mm
