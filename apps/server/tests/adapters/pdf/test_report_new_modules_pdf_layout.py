"""Focused tests for report PDF rendering and layout helpers."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm
from test_support.core import extract_pdf_text
from test_support.report_helpers import RUN_END, write_jsonl
from test_support.report_helpers import report_run_metadata as _run_metadata
from test_support.report_helpers import report_sample as _base_sample

from vibesensor.adapters.analysis_summary import summarize_log
from vibesensor.adapters.pdf.mapping import map_summary, prepare_report_input
from vibesensor.adapters.pdf.panels._panel_diagram import (
    assert_aspect_preserved,
    fit_rect_preserve_aspect,
)
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.adapters.pdf.pdf_style import (
    MARGIN,
    PAGE_H,
    PAGE_W,
    build_page1_layout,
    build_page2_layout,
    observed_signature_row_count,
)
from vibesensor.adapters.pdf.report_data import (
    NextStep,
    ReportTemplateData,
    VerdictPageData,
)


def _sample(
    idx: int,
    *,
    speed_kmh: float,
    dominant_freq_hz: float,
    peak_amp_g: float,
) -> dict[str, object]:
    return _base_sample(
        idx,
        speed_kmh=speed_kmh,
        dominant_freq_hz=dominant_freq_hz,
        peak_amp_g=peak_amp_g,
    )


def test_report_pdf_no_car_metadata(tmp_path: Path) -> None:
    run_path = tmp_path / "no_car.jsonl"
    records: list[dict[str, object]] = [_run_metadata()]
    for idx in range(15):
        records.append(_sample(idx, speed_kmh=50.0 + idx, dominant_freq_hz=14.0, peak_amp_g=0.08))
    records.append(RUN_END)
    write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    pdf = build_report_pdf(map_summary(prepare_report_input(summary)))
    assert pdf.startswith(b"%PDF")

    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2


def test_report_pdf_two_pages(tmp_path: Path) -> None:
    run_path = tmp_path / "two_pages.jsonl"
    records: list[dict[str, object]] = [_run_metadata(tire_circumference_m=2.2)]
    for idx in range(30):
        speed = 40 + idx
        wheel_hz = (speed * (1000.0 / 3600.0)) / 2.2
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    pdf = build_report_pdf(map_summary(prepare_report_input(summary)))
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2


def test_fit_rect_preserve_aspect_wider_box() -> None:
    x, y, w, h = fit_rect_preserve_aspect(100, 200, 0, 0, 400, 200)
    assert h == pytest.approx(200.0)
    assert w == pytest.approx(100.0)
    assert x == pytest.approx(150.0)


def test_fit_rect_preserve_aspect_taller_box() -> None:
    x, y, w, h = fit_rect_preserve_aspect(200, 100, 0, 0, 200, 400)
    assert w == pytest.approx(200.0)
    assert h == pytest.approx(100.0)
    assert y == pytest.approx(150.0)


def test_assert_aspect_preserved_ok() -> None:
    assert_aspect_preserved(100, 200, 50, 100)


def test_assert_aspect_preserved_fails() -> None:
    with pytest.raises(AssertionError, match="distorted"):
        assert_aspect_preserved(100, 200, 150, 100)


def test_assert_aspect_preserved_zero_dims() -> None:
    with pytest.raises(AssertionError, match="Invalid"):
        assert_aspect_preserved(0, 200, 50, 100)


def test_build_report_pdf_renders_data_trust_warning_detail() -> None:
    from test_support.report_helpers import minimal_summary

    summary = minimal_summary(
        lang="en",
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.82,
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.82,
            }
        ],
        run_suitability=[
            {
                "check": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "state": "warn",
            },
            {
                "check": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "pass",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(map_summary(prepare_report_input(summary)))
    page_one_text = " ".join(
        (PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split()
    )
    text = extract_pdf_text(pdf).lower()

    assert "inspect first — moderate confidence" in page_one_text
    assert "what to do next" in page_one_text
    assert "potential saturation samples detected" in page_one_text
    assert "run quality and limits" in text
    assert "frame integrity" in text


def test_build_report_pdf_renders_action_ready_status_on_page_one() -> None:
    pdf = build_report_pdf(
        ReportTemplateData(
            title="VibeSensor Diagnostic Report",
            verdict_page=VerdictPageData(
                suspected_source="Wheel / Tire",
                inspect_first="Front-Left",
                action_status="Action-ready",
                reason_sentence=(
                    "Wheel / Tire remains the strongest source because the repeated "
                    "pattern stayed strongest near Front-Left."
                ),
                dominant_corner="Front-Left",
                location_confidence="Strong",
                coverage_label="4 of 4 expected positions stayed connected.",
                proof_summary=(
                    "Front-Left outranked the next location by 2.1x on the p95 intensity map."
                ),
            ),
            next_steps=[
                NextStep(
                    action="Check wheel balance and runout",
                    why="The strongest repeated pattern stayed near the front-left wheel path.",
                    confirm=(
                        "If imbalance is the driver, the repeated pattern should "
                        "reduce after correction."
                    ),
                )
            ],
        )
    )
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split())

    assert "action-ready" in text
    assert "location confidence strong" in text
    assert "what to do next" in text


def test_build_report_pdf_renders_medium_confidence_data_trust_summary_for_tier_b() -> None:
    from test_support.report_helpers import minimal_summary

    summary = minimal_summary(
        lang="en",
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.65,
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.65,
            }
        ],
        run_suitability=[
            {
                "check": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "pass",
            },
            {
                "check": "SUITABILITY_CHECK_SPEED_VARIATION",
                "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "pass",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(map_summary(prepare_report_input(summary)))
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split())

    assert "inspect first — moderate confidence" in text
    assert "recapture before acting" not in text


def test_build_report_pdf_recapture_mode_moves_guidance_into_appendix_a() -> None:
    from test_support.report_helpers import minimal_summary

    summary = minimal_summary(
        lang="en",
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.82,
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.82,
            }
        ],
        run_suitability=[
            {
                "check": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
            },
            {
                "check": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "state": "warn",
            },
            {
                "check": "SUITABILITY_CHECK_SENSOR_COVERAGE",
                "check_key": "SUITABILITY_CHECK_SENSOR_COVERAGE",
                "state": "warn",
            },
            {
                "check": "SUITABILITY_CHECK_SPEED_VARIATION",
                "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "warn",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(map_summary(prepare_report_input(summary)))
    page_one_text = " ".join(
        (PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split()
    )
    text = extract_pdf_text(pdf).lower()

    assert "recapture before acting" in page_one_text
    assert "what was insufficient in this run" in text
    assert "conditions needed for a stronger result" in text


def test_build_page1_layout_prioritizes_observed_signature_panel() -> None:
    layout = build_page1_layout(
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
        header_content_height=14 * mm,
        observed_rows=5,
    )
    assert layout.observed.h > layout.header.h
    assert layout.systems.h < 50 * mm


def test_build_page2_layout_expands_evidence_space_and_keeps_continuation_room() -> None:
    layout = build_page2_layout(
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
        has_transient_findings=True,
        has_next_steps_continued=True,
    )
    assert layout.pattern_panel.h > 125 * mm
    assert layout.peaks_panel.h >= 58 * mm
    assert layout.observations_panel is not None
    assert layout.observations_panel.h < 24 * mm
    assert layout.continued_next_steps is not None
    assert layout.continued_next_steps.h > 16 * mm


def test_observed_signature_row_count_reserves_optional_reason_and_tier_a_warning() -> None:
    assert (
        observed_signature_row_count(
            certainty_tier_key="C",
            system_card_count=1,
            has_certainty_reason=False,
        )
        == 4
    )
    assert (
        observed_signature_row_count(
            certainty_tier_key="C",
            system_card_count=1,
            has_certainty_reason=True,
        )
        == 5
    )
    assert (
        observed_signature_row_count(
            certainty_tier_key="A",
            system_card_count=0,
            has_certainty_reason=False,
        )
        == 6
    )
