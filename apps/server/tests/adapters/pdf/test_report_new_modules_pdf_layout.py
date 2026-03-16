"""Focused tests for report PDF rendering and layout helpers."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from test_support.report_helpers import RUN_END, write_jsonl
from test_support.report_helpers import report_run_metadata as _run_metadata
from test_support.report_helpers import report_sample as _base_sample

from vibesensor.adapters.pdf.mapping import map_summary
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.adapters.pdf.pdf_page2 import assert_aspect_preserved, fit_rect_preserve_aspect
from vibesensor.use_cases.diagnostics import summarize_log


def _sample(idx: int, *, speed_kmh: float, dominant_freq_hz: float, peak_amp_g: float) -> dict:
    return _base_sample(
        idx,
        speed_kmh=speed_kmh,
        dominant_freq_hz=dominant_freq_hz,
        peak_amp_g=peak_amp_g,
    )


def test_report_pdf_no_car_metadata(tmp_path: Path) -> None:
    run_path = tmp_path / "no_car.jsonl"
    records: list[dict] = [_run_metadata()]
    for idx in range(15):
        records.append(_sample(idx, speed_kmh=50.0 + idx, dominant_freq_hz=14.0, peak_amp_g=0.08))
    records.append(RUN_END)
    write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    pdf = build_report_pdf(map_summary(summary))
    assert pdf.startswith(b"%PDF")

    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2


def test_report_pdf_two_pages(tmp_path: Path) -> None:
    run_path = tmp_path / "two_pages.jsonl"
    records: list[dict] = [_run_metadata(tire_circumference_m=2.2)]
    for idx in range(30):
        speed = 40 + idx
        wheel_hz = (speed * (1000.0 / 3600.0)) / 2.2
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    pdf = build_report_pdf(map_summary(summary))
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
        run_suitability=[
            {
                "check": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "state": "warn",
            },
            {
                "check": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
            },
        ],
        samples=[],
    )

    pdf = build_report_pdf(map_summary(summary))
    # Domain resolves via i18n with zeroed details (payload details not recovered)
    assert b"saturation" in pdf
    assert b"detected" in pdf
    assert b"dropped frames" in pdf
    assert b"queue overflows" in pdf
