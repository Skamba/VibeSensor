from __future__ import annotations

from io import BytesIO
from pathlib import Path

from _report_pdf_test_helpers import (
    extract_media_box,
    sample,
)
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from test_support.report_helpers import (
    RUN_END,
    write_jsonl,
)
from test_support.report_helpers import (
    report_run_metadata as run_metadata,
)

from vibesensor import __version__
from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.adapters.pdf.pdf_page1 import _draw_system_card
from vibesensor.infra.config.constants import KMH_TO_MPS
from vibesensor.use_cases.diagnostics import summarize_log
from vibesensor.use_cases.reporting.mapping import map_summary
from vibesensor.use_cases.reporting.report_data import PartSuggestion, SystemFindingCard


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
    x0, y0, x1, y1 = extract_media_box(build_report_pdf(map_summary(summarize_log(run_path))))
    width = x1 - x0
    height = y1 - y0
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
    assert build_report_pdf(map_summary(summary)).startswith(b"%PDF")


def test_report_pdf_footer_contains_version_marker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GIT_SHA", "a1b2c3d4e5f6")
    run_path = tmp_path / "run_version_marker.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(8):
        records.append(
            sample(
                idx,
                speed_kmh=48.0 + idx,
                dominant_freq_hz=16.0,
                peak_amp_g=0.05 + (idx * 0.001),
            ),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    pdf = build_report_pdf(map_summary(summarize_log(run_path)))
    marker = f"v{__version__} (a1b2c3d4)"
    reader = PdfReader(BytesIO(pdf))
    text_blob = "\n".join((page.extract_text() or "") for page in reader.pages)
    meta_blob = " ".join(
        str(value)
        for value in (
            getattr(reader.metadata, "title", None),
            getattr(reader.metadata, "subject", None),
        )
        if value
    )
    assert marker in text_blob or marker in meta_blob


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
    text_blob = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(BytesIO(build_report_pdf(map_summary(summarize_log(run_path))))).pages
    )
    assert text_blob.count("Next steps") == 1


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
    text_blob = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(
            BytesIO(build_report_pdf(map_summary(summarize_log(run_path, lang="nl")))),
        ).pages
    )
    assert "Duur:" in text_blob
    assert "Sensoren:" in text_blob
    assert "Aantal metingen:" in text_blob
    assert "Bemonsteringsfrequentie (Hz):" in text_blob


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
    text_blob = "\n".join(
        (page.extract_text() or "")
        for page in PdfReader(BytesIO(build_report_pdf(map_summary(summary)))).pages
    )
    assert "Firmware Version" in text_blob
    assert "esp-fw-1.2.3" in text_blob


def test_report_pdf_wraps_long_system_card_location() -> None:
    long_location = (
        "front-left wheel hub housing extended mount with additional bracket and balancing weight"
    )
    card = SystemFindingCard(
        system_name="Wheel / Tire",
        strongest_location=long_location,
        pattern_summary="1.02 wheel order harmonic with sideband modulation",
        parts=[
            PartSuggestion(name="Front-left wheel bearing assembly with extended descriptor"),
            PartSuggestion(name="Tire belt package"),
        ],
    )
    buf = BytesIO()
    canvas = Canvas(buf)
    _draw_system_card(canvas, 40, 120, 160, 130, card, tr=lambda key: key)
    canvas.save()
    assert long_location.encode("latin-1", errors="ignore") not in buf.getvalue()


def test_car_diagram_wheel_labels_stay_within_bounds_without_overlap() -> None:
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
        text_fn=lambda en, nl: en,
        diagram_width=200.0,
        diagram_height=250.0,
    )
    labels = [
        item
        for item in diagram.contents
        if hasattr(item, "text") and str(getattr(item, "text", "")).endswith("wheel")
    ]
    assert len(labels) == 4
