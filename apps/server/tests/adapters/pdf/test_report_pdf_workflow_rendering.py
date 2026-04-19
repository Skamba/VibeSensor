"""PDF rendering tests for report verdict, appendix flow, and page text."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from test_support.core import extract_pdf_text
from test_support.findings import make_finding_payload
from test_support.report_helpers import (
    RUN_END,
    ambiguous_primary_location_summary,
    minimal_summary,
    recapture_guidance_summary,
    sequential_same_source_summary,
    trunk_primary_guidance_summary,
    write_jsonl,
)
from test_support.report_helpers import report_run_metadata as _run_metadata
from test_support.report_helpers import report_sample as _base_sample

from vibesensor.adapters.analysis_summary import summarize_log
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.boundaries.reporting.document import (
    NextStep,
    ReportDocument,
    VerdictPageData,
)
from vibesensor.use_cases.history.report_document import build_report_document


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
    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    assert pdf.startswith(b"%PDF")

    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2


def test_report_pdf_includes_appendix_b_for_generated_summary(tmp_path: Path) -> None:
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
    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2


def test_report_pdf_action_ready_flow_includes_appendix_b_before_evidence() -> None:
    finding = make_finding_payload(
        finding_id="F_APPENDIX_B",
        suspected_source="wheel/tire",
        strongest_location="Front Left wheel",
        strongest_speed_band="60-80 km/h",
        confidence=0.82,
        frequency_hz_or_order="1x wheel order",
        signatures_observed=["1x wheel order"],
        matched_points=[
            {
                "speed_kmh": 62.0,
                "predicted_hz": 13.2,
                "matched_hz": 13.3,
                "location": "Front Left wheel",
                "amp": 0.10,
            },
            {
                "speed_kmh": 64.0,
                "predicted_hz": 13.6,
                "matched_hz": 13.7,
                "location": "Front Right wheel",
                "amp": 0.05,
            },
        ],
    )
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
        findings=[finding],
        top_causes=[finding],
    )

    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    reader = PdfReader(BytesIO(pdf))

    assert len(reader.pages) == 4
    page_two_text = reader.pages[1].extract_text() or ""
    assert "Sensor Topology" in page_two_text
    assert "Marker color shows relative vibration strength." in page_two_text
    assert "Appendix B" not in page_two_text
    assert "Evidence and Run Context" in (reader.pages[2].extract_text() or "")


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
                "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "state": "warn",
            },
            {
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "pass",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    page_one_text = " ".join(
        (PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split()
    )
    text = extract_pdf_text(pdf).lower()

    assert "inspect first — moderate confidence" in page_one_text
    assert "what to do next" in page_one_text
    assert "potential saturation samples detected" in page_one_text
    assert "run quality and limits" in text
    assert "frame integrity" in text


def test_build_report_pdf_replaces_limited_run_context_with_concrete_reason() -> None:
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
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 24.0, "mean_intensity_db": 20.0},
            {"location": "Front Right", "p95_intensity_db": 12.0, "mean_intensity_db": 9.0},
            {"location": "Rear Left", "p95_intensity_db": 9.0, "mean_intensity_db": 7.0},
            {"location": "Rear Right", "p95_intensity_db": 8.0, "mean_intensity_db": 6.0},
        ],
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.65,
                "strongest_location": "Front Left",
                "strongest_speed_band": "60-80 km/h",
                "dominance_ratio": 1.9,
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.65,
                "strongest_location": "Front Left",
                "strongest_speed_band": "60-80 km/h",
                "dominance_ratio": 1.9,
            }
        ],
        run_suitability=[
            {
                "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "state": "warn",
            },
            {
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "pass",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    page_one_text = " ".join(
        (PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split()
    )

    assert "limited by run context" not in page_one_text
    assert "speed was not steady during measurement" in page_one_text


def test_build_report_pdf_rephrases_ambiguous_primary_location_on_page_one() -> None:
    pdf = build_report_pdf(
        build_report_document(prepare_report_input(ambiguous_primary_location_summary()))
    )
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").split())

    assert "Mixed signal between Front-Left and Rear-Left" in text
    assert "Front-Left / Rear-Left" not in text


def test_build_report_pdf_avoids_trunk_specific_wheel_guidance_for_driveline_primary() -> None:
    pdf = build_report_pdf(
        build_report_document(
            prepare_report_input(trunk_primary_guidance_summary(primary_source="driveline"))
        )
    )
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").split())

    assert "Inspect propshaft runout/balance" in text
    assert "Check Trunk for tire damage" not in text
    assert "Check driveline components near Trunk" not in text


def test_build_report_pdf_renders_action_ready_status_on_page_one() -> None:
    pdf = build_report_pdf(
        ReportDocument(
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
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "pass",
            },
            {
                "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "pass",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split())

    assert "inspect first — moderate confidence" in text
    assert "recapture before acting" not in text


@pytest.mark.parametrize(
    ("source", "order_label", "source_label"),
    [
        pytest.param("engine", "2x engine order", "engine", id="engine"),
        pytest.param("driveline", "1x driveshaft order", "driveline", id="driveline"),
    ],
)
def test_build_report_pdf_keeps_weak_spatial_engine_and_driveline_findings_on_inspect_first_flow(
    source: str,
    order_label: str,
    source_label: str,
) -> None:
    from test_support.report_helpers import minimal_summary

    finding = {
        "finding_id": "F_ORDER",
        "suspected_source": source,
        "confidence": 0.65,
        "strongest_location": "Front Right",
        "strongest_speed_band": "40-70 km/h",
        "frequency_hz_or_order": order_label,
        "dominance_ratio": 1.04,
        "weak_spatial_separation": True,
    }
    summary = minimal_summary(
        lang="en",
        metadata={"car_info": {"tire_spec": "205/55R16"}},
        sensor_locations=["front_left", "front_right", "rear_left", "rear_right"],
        sensor_locations_connected_throughout=[
            "front_left",
            "front_right",
            "rear_left",
            "rear_right",
        ],
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 15.0, "peak_intensity_db": 18.8},
            {"location": "Front Right", "p95_intensity_db": 18.0, "peak_intensity_db": 22.0},
            {"location": "Rear Left", "p95_intensity_db": 15.4, "peak_intensity_db": 19.1},
            {"location": "Rear Right", "p95_intensity_db": 17.6, "peak_intensity_db": 21.5},
        ],
        findings=[finding],
        top_causes=[finding],
        run_suitability=[
            {
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "pass",
            },
            {
                "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "pass",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split())

    assert "inspect first — moderate confidence" in text
    assert "recapture before acting" not in text
    assert "insufficient evidence" not in text
    assert source_label in text


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
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
            },
            {
                "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "state": "warn",
            },
            {
                "check_key": "SUITABILITY_CHECK_SENSOR_COVERAGE",
                "state": "warn",
            },
            {
                "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "warn",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    page_one_text = " ".join(
        (PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").lower().split()
    )

    assert "recapture before acting" in page_one_text


def test_build_report_pdf_keeps_same_source_temporal_shift_visible_on_page_one() -> None:
    pdf = build_report_pdf(
        build_report_document(prepare_report_input(sequential_same_source_summary()))
    )
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").split())

    assert "Front-Left" in text
    assert "Rear-Right" in text
    assert "No single corner stayed dominant through the whole run" in text


def test_build_report_pdf_keeps_same_source_temporal_shift_visible_in_recapture_flow() -> None:
    pdf = build_report_pdf(
        build_report_document(
            prepare_report_input(sequential_same_source_summary(weak_spatial=True))
        )
    )
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").split())

    assert "Recapture before acting" in text
    assert "Front-Left" in text
    assert "Rear-Right" in text
    assert "No single corner stayed dominant through the whole run" in text


@pytest.mark.parametrize(
    ("mode", "expected_page_two_text"),
    [
        pytest.param(
            "steady",
            "Speed range never settled into a usable diagnostic band",
            id="steady-speed-page-two-guidance",
        ),
        pytest.param(
            "overlap",
            "Wheel / Tire and Driveline evidence overlapped",
            id="source-overlap-page-two-guidance",
        ),
        pytest.param(
            "weak",
            "Location evidence stayed spread across multiple positions",
            id="weak-location-page-two-guidance",
        ),
        pytest.param(
            "transient",
            "The strongest signal was transient or intermittent",
            id="transient-page-two-guidance",
        ),
    ],
)
def test_build_report_pdf_recapture_page_uses_scenario_specific_guidance(
    mode: str,
    expected_page_two_text: str,
) -> None:
    pdf = build_report_pdf(
        build_report_document(prepare_report_input(recapture_guidance_summary(mode)))
    )
    page_two_text = " ".join((PdfReader(BytesIO(pdf)).pages[1].extract_text() or "").split())

    assert expected_page_two_text in page_two_text
