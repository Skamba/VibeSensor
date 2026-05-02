"""Page-1 action preview regressions."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from test_support.report_helpers import minimal_summary

from vibesensor.adapters.pdf.page1_proof import _page1_diagram_findings
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.adapters.pdf.report_types import build_page1_render_plan
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.boundaries.reporting.document import (
    NextStep,
    ReportDocument,
    VerdictPageData,
)
from vibesensor.shared.boundaries.reporting.findings import FindingPresentation
from vibesensor.use_cases.history.report_document import build_report_document


def _page_one_text(pdf: bytes) -> str:
    return " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").split())


def test_page_one_long_wheel_action_does_not_silently_truncate() -> None:
    long_action = (
        "Check Front-Left tire for shoulder wear, belt shift, sidewall damage, flat spots, "
        "pressure mismatch, bent rim, or uneven wear before balancing."
    )

    text = _page_one_text(
        build_report_pdf(
            ReportDocument(
                title="VibeSensor Diagnostic Report",
                run_id="long-action-page-one",
                verdict_page=VerdictPageData(
                    suspected_source="Wheel / Tire",
                    inspect_first="Front-Left",
                    action_status="Inspect first \u2014 moderate confidence",
                    action_status_note="If first check is clean: Inspect Driveline next",
                    reason_sentence="Wheel / Tire stayed strongest near Front-Left.",
                    dominant_corner="Front-Left",
                    runner_up_corner="Front-Right",
                    dominance_ratio_label="2.1x stronger",
                    location_confidence="Moderate",
                    coverage_label="4 of 4 expected positions stayed connected.",
                    fallback_path="Inspect Driveline next",
                ),
                next_steps=[NextStep(action=long_action)],
            )
        )
    )

    assert "Check Front-Left tire for shoulder wear" in text
    assert "pressure mismatch" in text
    assert "before balancing" in text


def test_page_one_recapture_action_does_not_silently_truncate() -> None:
    recapture_action = (
        "Repeat the same speed band with separate drive/coast or load-change passes "
        "to separate the overlapping source paths."
    )

    text = _page_one_text(
        build_report_pdf(
            ReportDocument(
                title="VibeSensor Diagnostic Report",
                run_id="recapture-action-page-one",
                verdict_page=VerdictPageData(
                    suspected_source="Insufficient evidence",
                    action_status="Recapture before acting",
                    action_status_note="only summary-level evidence was available",
                    reason_sentence=(
                        "Wheel / Tire and Driveline evidence overlapped in the same window."
                    ),
                    dominant_corner="Front-Left",
                    runner_up_corner="Front-Right",
                    coverage_label="4 of 4 expected positions stayed connected.",
                    proof_panel_title="Best available location signal",
                ),
                next_steps=[NextStep(action=recapture_action)],
            )
        )
    )

    assert "Repeat the same speed band" in text
    assert "separate the overlapping source paths" in text


def test_page_one_generated_alternative_caveat_names_fallback_path() -> None:
    wheel = {
        "suspected_source": "wheel/tire",
        "confidence": 0.82,
        "strongest_location": "Front Left",
        "strongest_speed_band": "60-80 km/h",
    }
    driveline = {
        "suspected_source": "driveline",
        "confidence": 0.76,
        "strongest_location": "Rear Left",
        "strongest_speed_band": "60-80 km/h",
    }
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        speed_stats={"steady_speed": True},
        findings=[wheel, driveline],
        top_causes=[wheel, driveline],
    )

    document = build_report_document(prepare_report_input(summary))
    text = _page_one_text(build_report_pdf(document)).lower()

    assert document.verdict_page.action_status_note == (
        "If first check is clean: Inspect Driveline next"
    )
    assert "alternative source still in scope" not in text
    assert "if the primary path is clean" in text
    assert "inspect driveline next" in text
    assert text.count("inspect driveline next") == 1
    assert "source comparison" in text
    assert "engine" in text
    assert "not indicated" in text
    assert "record next" not in text


def test_page_one_reason_omits_unknown_duration_placeholder() -> None:
    wheel = {
        "suspected_source": "wheel/tire",
        "confidence": 0.82,
        "strongest_location": "Front Left",
        "strongest_speed_band": "60-80 km/h",
    }
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        speed_stats={"steady_speed": True},
        findings=[wheel],
        top_causes=[wheel],
    )

    text = _page_one_text(
        build_report_pdf(build_report_document(prepare_report_input(summary)))
    ).lower()

    assert "this unknown run" not in text
    assert "clearest repeatable vibration pattern" in text


def test_page_one_diagram_uses_verdict_dominant_corner() -> None:
    document = ReportDocument(
        verdict_page=VerdictPageData(
            suspected_source="Engine",
            dominant_corner="Front-Right",
        ),
        top_causes=[
            FindingPresentation(
                suspected_source="wheel/tire",
                strongest_location="Front Left",
                effective_confidence=0.84,
            ),
            FindingPresentation(
                suspected_source="engine",
                strongest_location="Front Right",
                effective_confidence=0.73,
            ),
        ],
    )

    diagram_findings = _page1_diagram_findings(build_page1_render_plan(document))

    assert diagram_findings == (
        {
            "strongest_location": "Front-Right",
            "suspected_source": "Engine",
        },
    )
