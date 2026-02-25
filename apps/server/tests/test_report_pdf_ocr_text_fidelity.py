from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from vibesensor.report import summarize_log
from vibesensor.report.pdf_builder import build_report_pdf

pdfium = pytest.importorskip("pypdfium2")
RapidOCR = pytest.importorskip("rapidocr_onnxruntime").RapidOCR


def _normalize_text(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"[|`~^*_]+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9%./:+-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _best_fuzzy_ratio(needle: str, haystack_lines: list[str]) -> tuple[float, str]:
    best_ratio = 0.0
    best_line = ""
    for line in haystack_lines:
        ratio = SequenceMatcher(a=needle, b=line).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_line = line
    return best_ratio, best_line


def _write_sparse_fixture(run_path: Path) -> None:
    records: list[dict[str, object]] = [
        {
            "record_type": "run_metadata",
            "schema_version": "v2-jsonl",
            "run_id": "run-ocr-hotspots",
            "start_time_utc": "2026-02-25T10:00:00+00:00",
            "end_time_utc": "2026-02-25T10:01:00+00:00",
            "sensor_model": "ADXL345",
            "raw_sample_rate_hz": 800,
            "feature_interval_s": 0.5,
            "fft_window_size_samples": 2048,
            "fft_window_type": "hann",
            "peak_picker_method": "max_peak_amp_across_axes",
            "accel_scale_g_per_lsb": 1.0 / 256.0,
            "tire_circumference_m": 2.2,
            "units": {
                "t_s": "s",
                "speed_kmh": "km/h",
                "accel_x_g": "g",
                "accel_y_g": "g",
                "accel_z_g": "g",
                "vibration_strength_db": "dB",
            },
            "amplitude_definitions": {
                "vibration_strength_db": {
                    "statistic": "Peak band RMS vs noise floor",
                    "units": "dB",
                    "definition": "20*log10((peak_band_rms + eps) / (floor + eps))",
                }
            },
            "incomplete_for_order_analysis": False,
        }
    ]

    for idx in range(36):
        speed_kmh = float(48 + (idx % 10))
        wheel_hz = (speed_kmh / 3.6) / 2.2
        if idx % 2 == 0:
            client_id = "fl01"
            client_name = "front-left wheel"
            db_value = 24.0
            peak_amp = 0.22
        else:
            client_id = "rr01"
            client_name = "rear-right wheel"
            db_value = 8.0
            peak_amp = 0.05
        records.append(
            {
                "record_type": "sample",
                "schema_version": "v2-jsonl",
                "run_id": "run-ocr-hotspots",
                "timestamp_utc": f"2026-02-25T10:00:{idx:02d}+00:00",
                "t_s": idx * 0.5,
                "client_id": client_id,
                "client_name": client_name,
                "speed_kmh": speed_kmh,
                "gps_speed_kmh": speed_kmh,
                "engine_rpm": None,
                "gear": None,
                "accel_x_g": 0.03 + (idx * 0.0003),
                "accel_y_g": 0.02 + (idx * 0.0002),
                "accel_z_g": 0.01 + (idx * 0.0002),
                "dominant_freq_hz": wheel_hz,
                "dominant_axis": "x",
                "top_peaks": [
                    {
                        "hz": wheel_hz,
                        "amp": peak_amp,
                        "vibration_strength_db": db_value,
                        "strength_bucket": "l2" if db_value > 20 else "l1",
                    }
                ],
                "vibration_strength_db": db_value,
                "strength_bucket": "l2" if db_value > 20 else "l1",
            }
        )

    records.append(
        {
            "record_type": "run_end",
            "schema_version": "v2-jsonl",
            "run_id": "run-ocr-hotspots",
        }
    )

    run_path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def test_report_pdf_ocr_text_fidelity_all_pages(tmp_path: Path) -> None:
    run_path = tmp_path / "ocr_sparse_session.jsonl"
    _write_sparse_fixture(run_path)
    summary = summarize_log(run_path)

    if isinstance(summary.get("findings"), list) and summary["findings"]:
        summary["findings"][0]["strongest_location"] = "front-left wheel"
        summary["findings"][0]["source"] = "wheel/tire"

    pdf_bytes = build_report_pdf(summary)

    audit_root_env = os.getenv("VIBESENSOR_OCR_AUDIT_DIR")
    artifact_dir = Path(audit_root_env) if audit_root_env else tmp_path
    artifact_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = artifact_dir / "ocr_sparse_session_report.pdf"
    pdf_path.write_bytes(pdf_bytes)

    document = pdfium.PdfDocument(str(pdf_path))
    ocr = RapidOCR()

    page_texts: list[str] = []
    page_lines: list[list[str]] = []
    screenshot_paths: list[str] = []
    for page_idx in range(len(document)):
        page = document[page_idx]
        bitmap = page.render(scale=3.2)
        page_image = bitmap.to_pil()
        image_path = artifact_dir / f"ocr_page_{page_idx + 1}.png"
        page_image.save(image_path)
        screenshot_paths.append(str(image_path))

        ocr_result, _ = ocr(bitmap.to_numpy())
        lines = [
            str(row[1]) for row in (ocr_result or []) if isinstance(row, list) and len(row) >= 2
        ]
        page_lines.append(lines)
        page_texts.append("\n".join(lines))

    expected_text = [
        "Diagnostic Worksheet",
        "Evidence and Hotspots",
        "Pattern Evidence",
        "Diagnostic Peaks",
        "Less vibration",
        "More vibration",
        "Finding source",
        "Wheel/Tire",
        "Driveline",
        "Engine",
        "front-left wheel",
        "rear-right wheel",
    ]

    normalized_pages = [_normalize_text(text) for text in page_texts]
    normalized_lines = [[_normalize_text(line) for line in lines] for lines in page_lines]

    checks: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for expected in expected_text:
        needle = _normalize_text(expected)
        best_ratio = 0.0
        best_line = ""
        found = False
        found_on_page: int | None = None

        for page_idx, page_text in enumerate(normalized_pages):
            if needle and needle in page_text:
                found = True
                found_on_page = page_idx + 1
                best_ratio = 1.0
                best_line = needle
                break
            ratio, line = _best_fuzzy_ratio(needle, normalized_lines[page_idx])
            if ratio > best_ratio:
                best_ratio = ratio
                best_line = line
                found_on_page = page_idx + 1

        min_ratio = 0.88 if len(needle) <= 8 else 0.76
        materially_truncated = bool(best_line) and len(best_line) < int(len(needle) * 0.62)
        passed = found or (best_ratio >= min_ratio and not materially_truncated)

        check = {
            "expected": expected,
            "normalized_expected": needle,
            "found": found,
            "best_ratio": round(best_ratio, 4),
            "best_match": best_line,
            "matched_page": found_on_page,
            "threshold": min_ratio,
            "materially_truncated": materially_truncated,
            "passed": passed,
        }
        checks.append(check)
        if not passed:
            failures.append(check)

    audit_payload = {
        "scenario": "sparse_session_two_connected_frontleft_active",
        "pdf": str(pdf_path),
        "screenshots": screenshot_paths,
        "expected_text": expected_text,
        "checks": checks,
        "failures": failures,
    }
    audit_path = artifact_dir / "ocr_text_audit.json"
    audit_path.write_text(json.dumps(audit_payload, indent=2), encoding="utf-8")

    assert not failures, f"OCR text fidelity failed; see {audit_path}"
