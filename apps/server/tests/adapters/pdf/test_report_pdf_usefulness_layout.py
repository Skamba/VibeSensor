from __future__ import annotations

from io import BytesIO

from _report_pdf_test_helpers import extract_pdf_pages_text
from pypdf import PdfReader
from test_support.pdf import extract_pdf_text

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
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


def _normalized_pdf_text(pdf_bytes: bytes) -> str:
    return " ".join(extract_pdf_text(pdf_bytes).split())


def test_page_one_keeps_action_ready_guidance_readable() -> None:
    data = ReportDocument(
        title="Action ready layout review",
        run_id="page-one-actions-readable",
        verdict_page=VerdictPageData(
            suspected_source="Wheel / Tire",
            inspect_first="Rear-Left",
            action_status="Action-ready",
            reason_sentence=(
                "Wheel / Tire remains the strongest source because repeatable "
                "energy stayed near Rear-Left during the steady-speed window."
            ),
            dominant_corner="Rear-Left",
            location_confidence="Strong",
            coverage_label="4 of 4 expected positions stayed connected.",
            proof_summary="Rear-Left outranked the next location by 2.1x.",
        ),
        next_steps=[
            NextStep(
                action=(
                    "Check Rear-Left for tire damage, flat spots, belt shift, "
                    "uneven wear, or pressure mismatch."
                ),
                why="Start with the strongest repeated corner before replacing parts.",
                confirm="A corrected tire should reduce the repeated order peak.",
                falsify="If clean, move to wheel runout and balance checks.",
            ),
            NextStep(
                action="Check Rear-Left for imbalance or radial/lateral runout.",
                why="Runout and imbalance are common wheel-speed vibration causes.",
                confirm="Repair should lower the Rear-Left matched peak.",
                falsify="If balance is clean, inspect driveline sources next.",
            ),
        ],
    )

    pdf = build_report_pdf(data)
    page_one_text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").split())
    report_text = _normalized_pdf_text(pdf)

    assert "What to do next" in page_one_text
    assert "Action-ready" in page_one_text
    assert "Rear-Left outranked the next location by 2.1x." in page_one_text
    assert "Check Rear-Left for tire damage" in page_one_text
    assert "pressure mismatch" in page_one_text
    assert "Check Rear-Left for imbalance" in report_text
    assert "driveline sources next" in report_text


def test_appendix_c_keeps_context_quality_and_traceability_visible() -> None:
    data = ReportDocument(
        title="Appendix C layout review",
        run_id="appendix-c-content-readable",
        appendix_c=AppendixCData(
            context_summary=(
                "A steady 100-110 km/h capture with all expected sensors connected "
                "is usable for source comparison."
            ),
            speed_band_summary="100-110 km/h",
            phase_summary="Cruise",
            observations=["Single repeatable observation near Rear-Left."],
            limits_summary=(
                "Treat this run as directional and rerun after the first inspection "
                "if the tire and wheel checks are clean."
            ),
            suitability_items=[
                DataTrustItem(
                    check="Frame integrity",
                    detail="No dropped frames or queue overflows detected.",
                    state="pass",
                ),
                DataTrustItem(
                    check="Speed stability",
                    detail="Speed stayed in the diagnostic band.",
                    state="pass",
                ),
            ],
        ),
        traceability_rows=[
            ReportLabelValueRow(label="Run ID", value="appendix-c-content-readable"),
            ReportLabelValueRow(label="Sensor Model", value="ADXL345"),
            ReportLabelValueRow(label="Analysis rows", value="124"),
        ],
    )

    pdf = build_report_pdf(data)
    pages_text = extract_pdf_pages_text(pdf)
    text = " ".join(pages_text)

    assert "A steady 100-110 km/h capture" in text
    assert "More context retained in source data." in text
    assert "Evidence and Run Context" in text
    assert "Traceability" in text
    assert "Frame integrity" in text
    assert "Speed stayed in the diagnostic band." in text
    assert "appendix-c-content-readable" in text
    assert "ADXL345" in text


def test_worksheet_keeps_ranked_sources_and_follow_up_actions_visible() -> None:
    data = ReportDocument(
        title="Worksheet layout review",
        run_id="worksheet-content-readable",
        appendix_a=AppendixAData(
            mode="workflow",
            primary_source="Engine",
            alternative_source="Wheel / Tire",
            why_primary_first="Engine-order evidence leads the workflow.",
            why_alternative_next="Wheel / Tire remains a plausible backup path.",
            next_if_clean="Move to the wheel and tire path if the engine checks are clean.",
            ranked_candidates=[
                RankedCandidateRow("Engine", inspect_first="Front-Right", path_role="Primary"),
                RankedCandidateRow("Wheel / Tire", inspect_first="Front-Left", path_role="Alt"),
                RankedCandidateRow("Driveline", inspect_first="Rear-Left", path_role="Third"),
                RankedCandidateRow("Body resonance", inspect_first="Cabin", path_role="Watch"),
            ],
        ),
        next_steps=[
            NextStep(
                action=f"Action {index}: inspect a unique worksheet item.",
                confirm=f"Confirm action {index}.",
                falsify=f"Falsify action {index}.",
            )
            for index in range(1, 9)
        ],
    )

    pages_text = extract_pdf_pages_text(build_report_pdf(data))
    text = " ".join(pages_text)

    assert "Engine-order evidence leads the workflow." in text
    assert "Primary vs alternative source" in text
    assert "Body resonance" in text
    for index in range(1, 9):
        assert f"Action {index}: inspect a unique worksheet item." in text
        assert f"Falsify action {index}." in text
