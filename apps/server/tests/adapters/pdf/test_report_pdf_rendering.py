"""Regression tests for PDF rendering, layout, and header/footer text output."""

from __future__ import annotations

from pathlib import Path

import pytest
from _report_pdf_test_helpers import (
    assert_pdf_contains,
    extract_media_box,
    extract_pdf_pages_text,
    sample,
)
from test_support.pdf import extract_pdf_text
from test_support.report_helpers import (
    RUN_END,
    minimal_summary,
    write_jsonl,
)
from test_support.report_helpers import (
    report_run_metadata as run_metadata,
)

from vibesensor.adapters.analysis_summary import summarize_log
from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.boundaries.reporting.document import AppendixAData, ReportDocument
from vibesensor.shared.constants.units import KMH_TO_MPS
from vibesensor.use_cases.history.report_document import build_report_document


def test_report_pdf_uses_a4_portrait_media_box(tmp_path: Path) -> None:
    run_path = tmp_path / "run_a4_portrait.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(12):
        records.append(
            sample(
                idx,
                speed_kmh=55.0 + idx,
                dominant_freq_hz=14.0 + (idx * 0.2),
                peak_amp_g=0.07 + (idx * 0.0006),
            ),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    x0, y0, x1, y1 = extract_media_box(
        build_report_pdf(
            build_report_document(prepare_report_input(summarize_log(run_path))),
        )
    )
    width = x1 - x0
    height = y1 - y0
    assert width == pytest.approx(595.276, abs=0.01)
    assert height == pytest.approx(841.89, abs=0.01)
    assert height > width


def test_report_pdf_allows_samples_without_strength_bucket(tmp_path: Path) -> None:
    run_path = tmp_path / "run_missing_strength_bucket.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(12):
        current_sample = sample(
            idx,
            speed_kmh=60.0 + idx,
            dominant_freq_hz=15.0 + (idx * 0.2),
            peak_amp_g=0.08 + (idx * 0.0004),
        )
        if idx % 3 == 0:
            current_sample["strength_bucket"] = None
        records.append(current_sample)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path, include_samples=False)
    assert summary["sensor_intensity_by_location"][0]["strength_bucket_distribution"]["total"] == 8
    rendered_pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    assert rendered_pdf.startswith(b"%PDF")
    assert_pdf_contains(rendered_pdf, "VibeSensor Diagnostic Report")
    assert "None" not in extract_pdf_text(rendered_pdf)


def test_report_pdf_worksheet_has_single_next_steps_heading(tmp_path: Path) -> None:
    run_path = tmp_path / "run_single_next_steps_heading.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800, tire_circumference_m=2.2)]
    for idx in range(14):
        speed = 55.0 + idx
        wheel_hz = (speed * KMH_TO_MPS) / 2.2
        records.append(
            sample(
                idx,
                speed_kmh=speed,
                dominant_freq_hz=wheel_hz,
                peak_amp_g=0.08 + (idx * 0.0005),
            ),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    pages_text = extract_pdf_pages_text(
        build_report_pdf(build_report_document(prepare_report_input(summarize_log(run_path)))),
    )
    text_blob = "\n".join(pages_text)
    assert text_blob.count("What to do next") == 1
    assert "What to do next" in pages_text[0]


def test_report_pdf_nl_localizes_header_metadata_labels(tmp_path: Path) -> None:
    run_path = tmp_path / "run_nl_header_metadata.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(10):
        current_sample = sample(
            idx,
            speed_kmh=50.0 + idx,
            dominant_freq_hz=15.0,
            peak_amp_g=0.06 + (idx * 0.0007),
        )
        current_sample["client_id"] = "client1234"
        records.append(current_sample)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    text_blob = extract_pdf_text(
        build_report_pdf(
            build_report_document(prepare_report_input(summarize_log(run_path, lang="nl"))),
        ),
    )
    assert "Duur" in text_blob
    assert "Sensoren" in text_blob
    assert "Analyserijen" in text_blob
    assert "Bemonsteringsfrequentie (Hz)" in text_blob


def test_report_pdf_header_contains_firmware_version(tmp_path: Path) -> None:
    run_path = tmp_path / "run_with_firmware.jsonl"
    records = [
        run_metadata(
            run_id="run-01",
            raw_sample_rate_hz=800,
            firmware_version="esp-fw-1.2.3",
        ),
    ]
    for idx in range(10):
        records.append(
            sample(
                idx,
                speed_kmh=50.0 + idx,
                dominant_freq_hz=15.0,
                peak_amp_g=0.06 + (idx * 0.0007),
            ),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path)
    text_blob = extract_pdf_text(
        build_report_pdf(build_report_document(prepare_report_input(summary)))
    )
    assert "Firmware Version" in text_blob
    assert "esp-fw-1.2.3" in text_blob
    assert "Raw Sample Rate (Hz)" in text_blob


def test_report_pdf_next_steps_do_not_leak_template_tokens() -> None:
    summary = minimal_summary(
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.74,
                "strongest_location": "front-left wheel",
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.74,
                "strongest_location": "front-left wheel",
            }
        ],
        test_plan=[
            {
                "action_id": "wheel_balance_and_runout",
                "what": "ACTION_WHEEL_BALANCE_WHAT",
                "why": "ACTION_WHEEL_BALANCE_WHY",
                "confirm": "ACTION_WHEEL_BALANCE_CONFIRM",
                "falsify": "ACTION_WHEEL_BALANCE_FALSIFY",
                "eta": "20-45 min",
            },
            {
                "action_id": "wheel_tire_condition",
                "what": "ACTION_TIRE_CONDITION_WHAT",
                "why": "ACTION_TIRE_CONDITION_WHY",
                "confirm": "ACTION_TIRE_CONDITION_CONFIRM",
                "falsify": "ACTION_TIRE_CONDITION_FALSIFY",
                "eta": "10-20 min",
            },
            {
                "action_id": "driveline_inspection",
                "what": "ACTION_DRIVELINE_INSPECTION_WHAT",
                "why": "ACTION_DRIVELINE_INSPECTION_WHY",
                "confirm": "ACTION_DRIVELINE_INSPECTION_CONFIRM",
                "falsify": "ACTION_DRIVELINE_INSPECTION_FALSIFY",
                "eta": "20-35 min",
            },
        ],
    )

    text_blob = extract_pdf_text(
        build_report_pdf(build_report_document(prepare_report_input(summary)))
    )

    assert "{wheel_focus}" not in text_blob
    assert "{speed_hint}" not in text_blob
    assert "{location_hint}" not in text_blob
    assert "{driveline_focus}" not in text_blob
    assert "Check Front-Left for imbalance or" in text_blob
    assert "runout" in text_blob
    assert "Check Front-Left for tire damage," in text_blob
    assert "pressure mismatch." in " ".join(text_blob.split())
    assert "Inspect propshaft runout/balance" not in text_blob
    assert "ETA:" not in text_blob


def test_report_pdf_rejects_invalid_certainty_tier_key() -> None:
    with pytest.raises(ValueError, match="certainty_tier_key"):
        build_report_pdf(
            ReportDocument(
                title="VibeSensor Diagnostic Report",
                run_id="run-invalid-tier",
                lang="en",
                certainty_tier_key="Z",
            )
        )


@pytest.mark.parametrize(
    ("document", "message"),
    [
        pytest.param(
            ReportDocument(title="", run_id="run-missing-title", lang="en"),
            "title must be non-empty",
            id="missing-title",
        ),
        pytest.param(
            ReportDocument(title="VibeSensor Diagnostic Report", run_id=None, lang="en"),
            "run_id must be non-empty",
            id="missing-run-id",
        ),
        pytest.param(
            ReportDocument(
                title="VibeSensor Diagnostic Report",
                run_id="run-missing-lang",
                lang=" ",
            ),
            "lang must be non-empty",
            id="missing-lang",
        ),
        pytest.param(
            ReportDocument(
                title="VibeSensor Diagnostic Report",
                run_id="run-bad-mode",
                lang="en",
                appendix_a=AppendixAData(mode="unexpected"),
            ),
            "appendix_a.mode",
            id="invalid-appendix-mode",
        ),
        pytest.param(
            ReportDocument(
                title="VibeSensor Diagnostic Report",
                run_id="run-negative-samples",
                lang="en",
                sample_count=-1,
            ),
            "sample_count must be non-negative",
            id="negative-sample-count",
        ),
    ],
)
def test_report_pdf_rejects_incomplete_report_document(
    document: ReportDocument,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_report_pdf(document)


def test_car_diagram_omits_sensor_labels() -> None:
    diagram = car_location_diagram(
        [{"strongest_location": "front-left wheel", "suspected_source": "wheel/tire"}],
        {
            "sensor_locations": [
                "front-left wheel",
                "front-right wheel",
                "rear-left wheel",
                "rear-right wheel",
            ],
        },
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        diagram_width=200.0,
        diagram_height=250.0,
    )
    labels = [
        item
        for item in diagram.contents
        if hasattr(item, "text")
        and str(getattr(item, "text", ""))
        in {
            "front-left wheel",
            "front-right wheel",
            "rear-left wheel",
            "rear-right wheel",
            "engine bay",
            "driver seat",
            "driveshaft tunnel",
            "trunk",
        }
    ]
    assert labels == []
    diagram_text = " ".join(
        str(getattr(item, "text", "")) for item in diagram.contents if hasattr(item, "text")
    )
    assert "FRONT" in diagram_text
    assert "REAR" in diagram_text
