"""Tests for new report modules: pattern_parts, strength_labels, aspect ratio, data model."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from vibesensor.report import summarize_log
from vibesensor.report.pattern_parts import parts_for_pattern, why_parts_listed
from vibesensor.report.pdf_builder import (
    assert_aspect_preserved,
    build_report_pdf,
    fit_rect_preserve_aspect,
)
from vibesensor.report.report_data import ReportTemplateData, map_summary
from vibesensor.report.strength_labels import certainty_label, strength_label, strength_text

# ---------------------------------------------------------------------------
# strength_label / strength_text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "db_val, expected_key",
    [
        (None, "unknown"),
        (0.0, "negligible"),
        (5.0, "negligible"),
        (8.0, "light"),
        (15.9, "light"),
        (16.0, "moderate"),
        (25.9, "moderate"),
        (26.0, "strong"),
        (35.9, "strong"),
        (36.0, "very_strong"),
        (100.0, "very_strong"),
    ],
)
def test_strength_label_bands(db_val: float | None, expected_key: str) -> None:
    key, label = strength_label(db_val, lang="en")
    assert key == expected_key
    assert isinstance(label, str) and label


def test_strength_label_nl() -> None:
    key, label = strength_label(20.0, lang="nl")
    assert key == "moderate"
    assert label == "Matig"


def test_strength_text_none() -> None:
    assert "Unknown" in strength_text(None, lang="en")


def test_strength_text_value() -> None:
    txt = strength_text(22.0, lang="en")
    assert "Moderate" in txt
    assert "22.0 dB" in txt


# ---------------------------------------------------------------------------
# certainty_label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "conf, expected_level",
    [
        (0.0, "low"),
        (0.39, "low"),
        (0.40, "medium"),
        (0.69, "medium"),
        (0.70, "high"),
        (1.0, "high"),
    ],
)
def test_certainty_label_levels(conf: float, expected_level: str) -> None:
    level, label, pct, reason = certainty_label(conf, lang="en")
    assert level == expected_level
    assert isinstance(label, str) and label
    assert "%" in pct
    assert isinstance(reason, str) and reason


def test_certainty_label_nl() -> None:
    _, label, _, _ = certainty_label(0.80, lang="nl")
    assert label == "Hoog"


def test_certainty_single_sensor_reason() -> None:
    _, _, _, reason = certainty_label(0.80, lang="en", sensor_count=1)
    assert "single sensor" in reason.lower()


def test_certainty_reference_gaps_reason() -> None:
    _, _, _, reason = certainty_label(0.80, lang="en", has_reference_gaps=True)
    assert "reference" in reason.lower()


def test_certainty_narrow_speed_reason() -> None:
    _, _, _, reason = certainty_label(0.80, lang="en", steady_speed=True)
    assert "speed" in reason.lower()


def test_certainty_weak_spatial_reason() -> None:
    _, _, _, reason = certainty_label(0.80, lang="en", weak_spatial=True)
    assert "spatial" in reason.lower()


# ---------------------------------------------------------------------------
# parts_for_pattern
# ---------------------------------------------------------------------------


def test_parts_for_wheel_1x() -> None:
    parts = parts_for_pattern("wheel/tire", "1x wheel order")
    assert len(parts) >= 2
    assert any("flat spot" in p.lower() or "bearing" in p.lower() for p in parts)


def test_parts_for_driveline_wildcard() -> None:
    parts = parts_for_pattern("driveline", None)
    assert len(parts) >= 2


def test_parts_for_engine_2x_nl() -> None:
    parts = parts_for_pattern("engine", "2x engine order", lang="nl")
    assert len(parts) >= 2
    # NL labels should be present
    assert all(isinstance(p, str) and p for p in parts)


def test_parts_for_unknown_system() -> None:
    parts = parts_for_pattern("unknown_system", "1x")
    assert len(parts) >= 1  # Should return default parts


def test_why_parts_listed_en() -> None:
    text = why_parts_listed("wheel/tire", "1x wheel order")
    assert "1x" in text
    assert "wheel" in text.lower()


def test_why_parts_listed_nl() -> None:
    text = why_parts_listed("engine", "2x engine order", lang="nl")
    assert "2x" in text
    assert "motor" in text.lower()


# ---------------------------------------------------------------------------
# PDF generation with missing car metadata
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def _run_metadata(run_id: str = "run-01", **kwargs) -> dict:
    defaults = {
        "record_type": "run_metadata",
        "schema_version": "v2-jsonl",
        "run_id": run_id,
        "start_time_utc": "2026-02-15T12:00:00+00:00",
        "end_time_utc": "2026-02-15T12:01:00+00:00",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 0.5,
        "fft_window_size_samples": 2048,
        "fft_window_type": "hann",
        "peak_picker_method": "max_peak_amp_across_axes",
        "accel_scale_g_per_lsb": 1.0 / 256.0,
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
    }
    defaults.update(kwargs)
    defaults.setdefault("incomplete_for_order_analysis", defaults.get("raw_sample_rate_hz") is None)
    return defaults


def _sample(idx: int, *, speed_kmh: float, dominant_freq_hz: float, peak_amp_g: float) -> dict:
    return {
        "record_type": "sample",
        "schema_version": "v2-jsonl",
        "run_id": "run-01",
        "timestamp_utc": f"2026-02-15T12:00:{idx:02d}+00:00",
        "t_s": idx * 0.5,
        "client_id": "c1",
        "client_name": "front-left wheel",
        "speed_kmh": speed_kmh,
        "gps_speed_kmh": speed_kmh,
        "engine_rpm": None,
        "gear": None,
        "accel_x_g": 0.03,
        "accel_y_g": 0.02,
        "accel_z_g": 0.01,
        "dominant_freq_hz": dominant_freq_hz,
        "dominant_axis": "x",
        "top_peaks": [
            {
                "hz": dominant_freq_hz,
                "amp": peak_amp_g,
                "vibration_strength_db": 22.0,
                "strength_bucket": "l2",
            },
        ],
        "vibration_strength_db": 22.0,
        "strength_bucket": "l2",
    }


def test_report_pdf_no_car_metadata(tmp_path: Path) -> None:
    """PDF gracefully handles summary without car_name/car_type metadata."""
    run_path = tmp_path / "no_car.jsonl"
    records: list[dict] = [_run_metadata()]
    for idx in range(15):
        records.append(_sample(idx, speed_kmh=50.0 + idx, dominant_freq_hz=14.0, peak_amp_g=0.08))
    records.append({"record_type": "run_end", "run_id": "run-01", "schema_version": "v2-jsonl"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    # No car metadata in summary
    pdf = build_report_pdf(summary)
    assert pdf.startswith(b"%PDF")

    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2


def test_report_pdf_two_pages(tmp_path: Path) -> None:
    """New layout generates exactly 2 pages."""
    run_path = tmp_path / "two_pages.jsonl"
    records: list[dict] = [_run_metadata(tire_circumference_m=2.2)]
    for idx in range(30):
        speed = 40 + idx
        wheel_hz = (speed * (1000.0 / 3600.0)) / 2.2
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09)
        )
    records.append({"record_type": "run_end", "run_id": "run-01", "schema_version": "v2-jsonl"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    pdf = build_report_pdf(summary)
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2


# ---------------------------------------------------------------------------
# Aspect ratio preservation (from template spec)
# ---------------------------------------------------------------------------


def test_fit_rect_preserve_aspect_wider_box() -> None:
    """Box wider than source → fit to height, center horizontally."""
    x, y, w, h = fit_rect_preserve_aspect(100, 200, 0, 0, 400, 200)
    assert h == pytest.approx(200.0)
    assert w == pytest.approx(100.0)
    assert x == pytest.approx(150.0)  # centered


def test_fit_rect_preserve_aspect_taller_box() -> None:
    """Box taller than source → fit to width, center vertically."""
    x, y, w, h = fit_rect_preserve_aspect(200, 100, 0, 0, 200, 400)
    assert w == pytest.approx(200.0)
    assert h == pytest.approx(100.0)
    assert y == pytest.approx(150.0)


def test_assert_aspect_preserved_ok() -> None:
    assert_aspect_preserved(100, 200, 50, 100)  # ratio 0.5


def test_assert_aspect_preserved_fails() -> None:
    with pytest.raises(AssertionError, match="distorted"):
        assert_aspect_preserved(100, 200, 150, 100)  # very different ratio


def test_assert_aspect_preserved_zero_dims() -> None:
    with pytest.raises(AssertionError, match="Invalid"):
        assert_aspect_preserved(0, 200, 50, 100)


# ---------------------------------------------------------------------------
# map_summary data model
# ---------------------------------------------------------------------------


def test_map_summary_basic(tmp_path: Path) -> None:
    """map_summary produces a valid ReportTemplateData with expected fields."""
    run_path = tmp_path / "map_summary.jsonl"
    records: list[dict] = [_run_metadata(tire_circumference_m=2.2)]
    for idx in range(20):
        speed = 50 + idx
        wheel_hz = (speed * (1000.0 / 3600.0)) / 2.2
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09)
        )
    records.append({"record_type": "run_end", "run_id": "run-01", "schema_version": "v2-jsonl"})
    _write_jsonl(run_path, records)
    summary = summarize_log(run_path)

    data = map_summary(summary)
    assert isinstance(data, ReportTemplateData)
    assert data.title  # not empty
    assert data.run_datetime
    assert data.observed.primary_system
    assert data.observed.certainty_label
    assert data.observed.certainty_reason
    assert data.version_marker


def test_map_summary_no_top_causes() -> None:
    """map_summary handles empty summary gracefully."""
    summary: dict = {
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }
    data = map_summary(summary)
    assert isinstance(data, ReportTemplateData)
    assert data.system_cards == []
    assert data.next_steps == []


def test_most_likely_origin_summary_weak_spatial_disambiguates_location() -> None:
    from vibesensor.report.summary import _most_likely_origin_summary

    findings = [
        {
            "strongest_location": "Rear Left",
            "location_hotspot": {
                "ambiguous_locations": ["Rear Left", "Front Right"],
                "second_location": "Front Right",
            },
            "suspected_source": "wheel/tire",
            "dominance_ratio": 1.05,
            "weak_spatial_separation": True,
            "strongest_speed_band": "80-90 km/h",
            "confidence_0_to_1": 0.81,
        },
        {
            "strongest_location": "Front Right",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.74,
        },
    ]

    origin = _most_likely_origin_summary(findings, "en")

    assert origin["weak_spatial_separation"] is True
    assert origin["location"] == "Rear Left / Front Right"
    assert origin["alternative_locations"] == ["Front Right"]


def test_map_summary_observed_uses_disambiguated_origin_location() -> None:
    summary: dict = {
        "lang": "en",
        "top_causes": [
            {
                "source": "wheel/tire",
                "strongest_location": "Rear Left",
                "strongest_speed_band": "80-90 km/h",
                "confidence": 0.83,
                "weak_spatial_separation": True,
                "signatures_observed": ["1x wheel order"],
                "confidence_tone": "warn",
            }
        ],
        "most_likely_origin": {
            "location": "Rear Left / Front Right",
            "alternative_locations": ["Front Right"],
            "explanation": "Weak spatial separation.",
        },
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }

    data = map_summary(summary)

    assert data.observed.strongest_sensor_location == "Rear Left / Front Right"


def test_map_summary_peak_rows_use_persistence_metrics() -> None:
    summary: dict = {
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 33.0,
                    "order_label": "",
                    "max_amp_g": 0.9,
                    "p95_amp_g": 0.12,
                    "presence_ratio": 0.85,
                    "persistence_score": 0.0867,
                    "peak_classification": "patterned",
                    "typical_speed_band": "60-80 km/h",
                }
            ]
        },
    }
    data = map_summary(summary)
    assert data.peak_rows
    row = data.peak_rows[0]
    assert row.amp_g == "0.1200"
    assert "patterned" in row.relevance
    assert "85%" in row.relevance


def test_map_summary_data_trust_keeps_warning_detail() -> None:
    summary: dict = {
        "lang": "nl",
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [
            {
                "check": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
                "explanation": "3 dropped frames, 2 queue overflows detected.",
            }
        ],
        "plots": {},
    }
    data = map_summary(summary)
    assert data.data_trust
    assert data.data_trust[0].state == "warn"
    assert data.data_trust[0].check == "Frame-integriteit"
    assert data.data_trust[0].detail == "3 dropped frames, 2 queue overflows detected."


def test_map_summary_data_trust_supports_legacy_literal_check_labels() -> None:
    summary: dict = {
        "lang": "nl",
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [
            {
                "check": "Frame integrity",
                "state": "warn",
                "explanation": "3 dropped frames, 2 queue overflows detected.",
            }
        ],
        "plots": {},
    }
    data = map_summary(summary)
    assert data.data_trust
    assert data.data_trust[0].check == "Frame integrity"


def test_map_summary_data_trust_check_labels_follow_lang_for_same_summary_data() -> None:
    base_summary: dict = {
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [
            {
                "check": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "pass",
                "explanation": "Wide enough speed sweep for order tracking.",
            }
        ],
        "plots": {},
    }

    summary_en = {**base_summary, "lang": "en"}
    summary_nl = {**base_summary, "lang": "nl"}

    data_en = map_summary(summary_en)
    data_nl = map_summary(summary_nl)

    assert data_en.data_trust[0].check == "Speed variation"
    assert data_nl.data_trust[0].check == "Snelheidsvariatie"


def test_build_report_pdf_renders_data_trust_warning_detail() -> None:
    summary: dict = {
        "lang": "en",
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [
            {
                "check": "Saturation and outliers",
                "state": "warn",
                "explanation": "5 potential saturation samples detected.",
            },
            {
                "check": "Frame integrity",
                "state": "warn",
                "explanation": "3 dropped frames, 2 queue overflows detected.",
            },
        ],
        "plots": {},
        "samples": [],
    }

    pdf = build_report_pdf(summary)
    assert b"5 potential saturation samples detected." in pdf
    assert b"3 dropped frames, 2 queue overflows detected." in pdf
