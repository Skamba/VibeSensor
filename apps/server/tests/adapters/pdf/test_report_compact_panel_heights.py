from __future__ import annotations

from reportlab.lib.units import mm

from vibesensor.adapters.pdf.page1_actions import estimate_actions_block_height
from vibesensor.adapters.pdf.pdf_appendices import (
    _estimate_action_steps_panel_height,
    _estimate_appendix_c_context_panel_height,
    _estimate_appendix_c_suitability_panel_height,
    _estimate_appendix_c_trace_panel_height,
    _estimate_worksheet_ranked_stack_height,
    _estimate_worksheet_top_panel_height,
    _worksheet_first_actions_panel_height,
)
from vibesensor.adapters.pdf.pdf_style import GAP, MARGIN, PAGE_H, PAGE_W, PANEL_HEADER_H
from vibesensor.adapters.pdf.report_types import (
    build_appendix_c_render_plan,
    build_page1_render_plan,
)
from vibesensor.report_i18n import tr as i18n_tr
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixCData,
    DataTrustItem,
    NextStep,
    RankedCandidateRow,
    ReportDocument,
    ReportLabelValueRow,
    VerdictPageData,
)


def _tr(key: str, **kwargs: object) -> str:
    return i18n_tr("en", key, **kwargs)


def test_estimate_actions_block_height_shrinks_for_short_content() -> None:
    data = ReportDocument(
        lang="en",
        verdict_page=VerdictPageData(),
        next_steps=[
            NextStep(action="Check wheel balance", why="Short reason"),
        ],
    )
    page_top = PAGE_H - MARGIN
    content_bottom = MARGIN + 8 * mm
    main_h = page_top - content_bottom - (26 * mm) - (40 * mm) - (2 * GAP)
    actions_h = estimate_actions_block_height(build_page1_render_plan(data), tr=_tr, w=78 * mm)

    assert actions_h < main_h
    assert actions_h >= PANEL_HEADER_H


def test_estimate_actions_block_height_reserves_page_one_check_flow() -> None:
    width = PAGE_W - 2 * MARGIN
    actions_w = width - (width * 0.58) - GAP
    data = ReportDocument(
        lang="en",
        verdict_page=VerdictPageData(),
        next_steps=[
            NextStep(
                action=(
                    "Check Rear-Left for tire damage, flat spots, belt shift, uneven wear, "
                    "or pressure mismatch."
                )
            ),
            NextStep(action="Check Rear-Left for imbalance or radial/lateral runout."),
        ],
    )

    actions_h = estimate_actions_block_height(build_page1_render_plan(data), tr=_tr, w=actions_w)

    assert 110 * mm < actions_h < 125 * mm
    assert actions_h >= PANEL_HEADER_H


def test_estimate_appendix_c_lower_panels_shrink_for_short_content() -> None:
    data = ReportDocument(
        lang="en",
        verdict_page=VerdictPageData(action_status_note="skip duplicate"),
        appendix_c=AppendixCData(
            context_summary="Short context note.",
            speed_band_summary="100-110 km/h.",
            phase_summary="Cruise only.",
            observations=["Single repeatable observation."],
            limits_summary="Run quality was acceptable.",
            suitability_items=[
                DataTrustItem(
                    check="Frame integrity",
                    detail="Passed cleanly.",
                    state="pass",
                ),
                DataTrustItem(
                    check="Speed stability",
                    detail="Within expected range.",
                    state="pass",
                ),
            ],
        ),
        traceability_rows=[
            ReportLabelValueRow(
                label="Evidence",
                value="One short traceability note.",
            ),
        ],
    )

    plan = build_appendix_c_render_plan(data)
    context_h = _estimate_appendix_c_context_panel_height(plan, width=44 * mm)
    suitability_h = _estimate_appendix_c_suitability_panel_height(plan, width=56 * mm)
    trace_h = _estimate_appendix_c_trace_panel_height(plan, width=72 * mm)

    assert max(context_h, suitability_h, trace_h) < 90 * mm
    assert min(context_h, suitability_h, trace_h) >= 34 * mm


def test_estimate_appendix_c_lower_panels_stay_tighter_for_unbalanced_card_content() -> None:
    data = ReportDocument(
        lang="en",
        verdict_page=VerdictPageData(action_status_note="skip duplicate"),
        appendix_c=AppendixCData(
            context_summary=(
                "A steady 100-110 km/h capture with 4 of 4 expected wheel positions connected "
                "makes this run usable for source comparison."
            ),
            speed_band_summary="100-110 km/h",
            phase_summary="Cruise",
            observations=[],
            limits_summary=(
                "Treat this run as directional, not final. If the first inspection is clean, "
                "rerun with a longer steady hold plus accel/decel and drive/coast comparison "
                "through the 100-110 km/h band."
            ),
            suitability_items=[
                DataTrustItem(
                    check="Speed variation",
                    detail=(
                        "Speed range stayed in a usable diagnostic band for steady-state "
                        "diagnosis and order tracking."
                    ),
                    state="pass",
                ),
                DataTrustItem(
                    check="Sensor coverage",
                    detail="Multiple sensor locations observed.",
                    state="pass",
                ),
                DataTrustItem(
                    check="Reference completeness",
                    detail="Required order references are present.",
                    state="pass",
                ),
                DataTrustItem(
                    check="Saturation and outliers",
                    detail="No obvious saturation detected.",
                    state="pass",
                ),
                DataTrustItem(
                    check="Frame integrity",
                    detail="No dropped frames or queue overflows detected.",
                    state="pass",
                ),
            ],
        ),
        traceability_rows=[
            ReportLabelValueRow(label="Run date", value="2026-04-01 01:05:30 UTC"),
            ReportLabelValueRow(label="Run ID", value="a2d18c88451f4d688b61e60b48d9949b"),
            ReportLabelValueRow(label="tire size", value="285/30R21"),
            ReportLabelValueRow(label="Sensor Model", value="ADXL345"),
            ReportLabelValueRow(label="Firmware Version", value="sim-0.2"),
            ReportLabelValueRow(label="Analysis rows", value="124"),
            ReportLabelValueRow(label="Raw Sample Rate (Hz)", value="800"),
        ],
    )

    width = PAGE_W - 2 * MARGIN
    context_w = width * 0.24
    suitability_w = width * 0.31
    trace_w = width - context_w - suitability_w - (2 * GAP)

    plan = build_appendix_c_render_plan(data)
    context_h = _estimate_appendix_c_context_panel_height(plan, width=context_w)
    suitability_h = _estimate_appendix_c_suitability_panel_height(plan, width=suitability_w)
    trace_h = _estimate_appendix_c_trace_panel_height(plan, width=trace_w)

    assert context_h < trace_h
    assert suitability_h < trace_h
    assert trace_h < 72 * mm


def test_estimate_worksheet_summary_panels_shrink_for_short_content() -> None:
    appendix = AppendixAData(
        primary_source="Wheel / Tire",
        alternative_source="Driveline",
        why_primary_first="Short reason.",
        why_alternative_next="Backup reason.",
        next_if_clean="Move to the alternative path.",
        ranked_candidates=[
            RankedCandidateRow(
                source_name="Wheel / Tire",
                inspect_first="Front-left wheel",
                path_role="Primary",
            ),
            RankedCandidateRow(
                source_name="Driveline",
                inspect_first="Propshaft",
                path_role="Alternative",
            ),
            RankedCandidateRow(
                source_name="Engine",
                inspect_first="Accessory drive",
                path_role="Third",
            ),
        ],
    )

    top_h = _estimate_worksheet_top_panel_height(appendix, lang="en")
    stack_h = _estimate_worksheet_ranked_stack_height(appendix, lang="en")

    assert top_h < 56 * mm
    assert stack_h <= 62 * mm


def test_estimate_worksheet_action_panel_shrinks_for_short_content() -> None:
    appendix = AppendixAData(
        primary_source="Wheel / Tire",
        alternative_source="Driveline",
        why_primary_first="Short reason.",
        why_alternative_next="Backup reason.",
        next_if_clean="Move to the alternative path.",
    )
    steps = [
        NextStep(action="Check wheel balance", why="Start with the corner that won the ranking."),
        NextStep(
            action="Inspect tire condition",
            why="Look for the simplest repeatable fault first.",
        ),
        NextStep(
            action="Move to the backup path if clean",
            why="Keep the alternative source active.",
        ),
    ]

    max_panel_h = _worksheet_first_actions_panel_height(appendix, lang="en")
    panel_h = _estimate_action_steps_panel_height(steps, width=PAGE_W - 2 * MARGIN)

    assert panel_h < max_panel_h
    assert panel_h >= PANEL_HEADER_H
