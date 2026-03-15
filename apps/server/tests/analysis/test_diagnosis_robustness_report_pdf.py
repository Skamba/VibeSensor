from __future__ import annotations

from io import BytesIO
from typing import Any

from pypdf import PdfReader
from test_support import (
    ALL_SENSORS,
    extract_pdf_text,
    make_sample,
    standard_metadata,
    wheel_hz,
)

from vibesensor.use_cases.diagnostics import summarize_run_data
from vibesensor.adapters.pdf.mapping import map_summary


class TestPdfContentForDiagnosedScenario:
    def test_pdf_contains_diagnosis_content(self) -> None:
        whz = wheel_hz(100.0)
        samples: list[dict[str, Any]] = []
        for i in range(40):
            for sensor in ALL_SENSORS:
                if sensor == "front-left":
                    peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=100.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    ),
                )

        from vibesensor.adapters.pdf.pdf_engine import build_report_pdf

        summary = summarize_run_data(
            standard_metadata(language="en"),
            samples,
            lang="en",
            file_name="pdf_diag_test",
        )
        pdf_bytes = build_report_pdf(map_summary(summary))
        text_lower = extract_pdf_text(pdf_bytes).lower()
        assert "diagnostic worksheet" in text_lower
        assert "wheel" in text_lower or "tire" in text_lower
        assert "front" in text_lower
        assert "km/h" in text_lower
        assert "db" in text_lower
        assert len(PdfReader(BytesIO(pdf_bytes)).pages) >= 1

    def test_pdf_nl_contains_dutch_diagnosis(self) -> None:
        whz = wheel_hz(80.0)
        samples: list[dict[str, Any]] = []
        for i in range(30):
            for sensor in ALL_SENSORS:
                if sensor == "rear-right":
                    peaks = [{"hz": whz, "amp": 0.06}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    ),
                )

        from vibesensor.adapters.pdf.pdf_engine import build_report_pdf

        summary = summarize_run_data(
            standard_metadata(language="nl"),
            samples,
            lang="nl",
            file_name="pdf_nl_diag",
        )
        text_lower = extract_pdf_text(build_report_pdf(map_summary(summary))).lower()
        assert "diagnostisch werkformulier" in text_lower
        assert "km/h" in text_lower
