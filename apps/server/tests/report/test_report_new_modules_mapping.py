"""Focused tests for report summary mapping and origin explanation behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_support.report_helpers import RUN_END, minimal_summary, write_jsonl
from test_support.report_helpers import report_run_metadata as _run_metadata
from test_support.report_helpers import report_sample as _base_sample

from vibesensor.analysis import summarize_log
from vibesensor.analysis.summary_builder import summarize_origin
from vibesensor.report.mapping import map_summary
from vibesensor.report.report_data import ReportTemplateData


def _sample(idx: int, *, speed_kmh: float, dominant_freq_hz: float, peak_amp_g: float) -> dict:
    return _base_sample(
        idx,
        speed_kmh=speed_kmh,
        dominant_freq_hz=dominant_freq_hz,
        peak_amp_g=peak_amp_g,
    )


def _assert_no_phase_onset(explanation: object) -> None:
    if isinstance(explanation, list):
        assert not any(
            isinstance(part, dict) and part.get("_i18n_key") == "ORIGIN_PHASE_ONSET_NOTE"
            for part in explanation
        )
    else:
        assert isinstance(explanation, dict)


def test_map_summary_basic(tmp_path: Path) -> None:
    run_path = tmp_path / "map_summary.jsonl"
    records: list[dict] = [_run_metadata(tire_circumference_m=2.2)]
    for idx in range(20):
        speed = 50 + idx
        wheel_hz = (speed * (1000.0 / 3600.0)) / 2.2
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path)

    data = map_summary(summary)
    assert isinstance(data, ReportTemplateData)
    assert data.title
    assert data.run_datetime
    assert data.observed.primary_system
    assert data.observed.certainty_label
    assert data.observed.certainty_reason
    assert data.version_marker


def test_map_summary_no_top_causes() -> None:
    summary = minimal_summary()
    data = map_summary(summary)
    assert isinstance(data, ReportTemplateData)
    assert data.system_cards == []
    assert data.certainty_tier_key == "A"
    assert len(data.next_steps) >= 1


def test_map_summary_uses_connected_sensors_for_report_evidence() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=["Front Left", "Rear Left"],
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 10.0},
            {"location": "Rear Left", "p95_intensity_db": 9.0},
            {"location": "Front Right", "p95_intensity_db": 18.0},
        ],
    )

    data = map_summary(summary)
    assert data.sensor_count == 2
    assert data.sensor_locations == ["Front Left", "Rear Left"]
    assert [row["location"] for row in data.sensor_intensity_by_location] == [
        "Front Left",
        "Rear Left",
    ]


def test_most_likely_origin_summary_weak_spatial_disambiguates_location() -> None:
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
            "confidence": 0.81,
        },
        {
            "strongest_location": "Front Right",
            "suspected_source": "wheel/tire",
            "confidence": 0.74,
        },
    ]

    origin = summarize_origin(findings)
    assert origin["location"] == "Rear Left / Front Right"
    assert origin["alternative_locations"] == ["Front Right"]


@pytest.mark.parametrize(
    ("phase", "location", "speed_band", "confidence"),
    [
        ("acceleration", "Front Right", "60-80 km/h", 0.75),
        ("deceleration", "Rear Left", "40-60 km/h", 0.70),
    ],
    ids=["acceleration_en", "deceleration_nl"],
)
def test_most_likely_origin_summary_phase_onset(
    phase: str,
    location: str,
    speed_band: str,
    confidence: float,
) -> None:
    findings = [
        {
            "strongest_location": location,
            "suspected_source": "wheel/tire",
            "dominance_ratio": 2.5,
            "weak_spatial_separation": False,
            "strongest_speed_band": speed_band,
            "dominant_phase": phase,
            "confidence": confidence,
        },
    ]

    origin = summarize_origin(findings)

    assert origin["dominant_phase"] == phase
    explanation = origin["explanation"]
    assert isinstance(explanation, list)
    assert any(
        isinstance(part, dict)
        and part.get("_i18n_key") == "ORIGIN_PHASE_ONSET_NOTE"
        and part.get("phase") == phase
        for part in explanation
    )


def test_most_likely_origin_summary_no_phase_onset_for_cruise() -> None:
    findings = [
        {
            "strongest_location": "Front Left",
            "suspected_source": "wheel/tire",
            "dominance_ratio": 3.0,
            "weak_spatial_separation": False,
            "strongest_speed_band": "80-100 km/h",
            "dominant_phase": "cruise",
            "confidence": 0.80,
        },
    ]

    origin = summarize_origin(findings)
    _assert_no_phase_onset(origin["explanation"])


def test_most_likely_origin_summary_no_phase_onset_when_absent() -> None:
    findings = [
        {
            "strongest_location": "Front Left",
            "suspected_source": "wheel/tire",
            "dominance_ratio": 3.0,
            "weak_spatial_separation": False,
            "strongest_speed_band": "80-100 km/h",
            "confidence": 0.80,
        },
    ]

    origin = summarize_origin(findings)

    assert origin["dominant_phase"] is None
    _assert_no_phase_onset(origin["explanation"])

    summary = minimal_summary(
        lang="en",
        top_causes=[
            {
                "suspected_source": "wheel/tire",
                "strongest_location": "Rear Left",
                "strongest_speed_band": "80-90 km/h",
                "confidence": 0.83,
                "weak_spatial_separation": True,
                "signatures_observed": ["1x wheel order"],
                "confidence_tone": "warn",
            },
        ],
        most_likely_origin={
            "location": "Rear Left / Front Right",
            "alternative_locations": ["Front Right"],
            "explanation": "Weak spatial separation.",
        },
    )

    data = map_summary(summary)
    assert data.observed.strongest_location == "Rear Left / Front Right"


def test_map_summary_peak_rows_use_persistence_metrics() -> None:
    summary = minimal_summary(
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 33.0,
                    "order_label": "",
                    "max_intensity_db": 22.0,
                    "p95_intensity_db": 18.4,
                    "strength_db": 18.4,
                    "presence_ratio": 0.85,
                    "persistence_score": 0.0867,
                    "peak_classification": "patterned",
                    "typical_speed_band": "60-80 km/h",
                },
            ],
        },
    )
    data = map_summary(summary)
    assert data.peak_rows
    row = data.peak_rows[0]
    assert row.peak_db == "18.4"
    assert row.strength_db == "18.4"
    assert "patterned" in row.relevance
    assert "85%" in row.relevance


def test_map_summary_peak_rows_render_baseline_noise_label() -> None:
    summary = minimal_summary(
        lang="en",
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 18.0,
                    "order_label": "",
                    "max_intensity_db": 2.1,
                    "p95_intensity_db": 2.1,
                    "strength_db": 2.1,
                    "presence_ratio": 0.1,
                    "persistence_score": 0.001,
                    "peak_classification": "baseline_noise",
                    "typical_speed_band": "any",
                },
            ],
        },
    )
    data = map_summary(summary)
    assert data.peak_rows
    assert "noise floor" in data.peak_rows[0].relevance


def test_map_summary_data_trust_keeps_warning_detail() -> None:
    summary = minimal_summary(
        lang="nl",
        run_suitability=[
            {
                "check": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
                "explanation": "3 dropped frames, 2 queue overflows detected.",
            },
        ],
    )
    data = map_summary(summary)
    assert data.data_trust
    assert data.data_trust[0].state == "warn"
    assert data.data_trust[0].check == "Frame-integriteit"
    assert data.data_trust[0].detail == "3 dropped frames, 2 queue overflows detected."


def test_map_summary_data_trust_literal_check_labels() -> None:
    summary = minimal_summary(
        lang="nl",
        run_suitability=[
            {
                "check": "Frame integrity",
                "state": "warn",
                "explanation": "3 dropped frames, 2 queue overflows detected.",
            },
        ],
    )
    data = map_summary(summary)
    assert data.data_trust
    assert data.data_trust[0].check == "Frame integrity"


def test_map_summary_data_trust_includes_run_context_warnings() -> None:
    summary = minimal_summary(
        lang="en",
        warnings=[
            {
                "code": "reference_context_incomplete",
                "severity": "warn",
                "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
                "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
            },
        ],
    )
    data = map_summary(summary)
    assert any(
        item.check == "Order-analysis reference context was incomplete for this run"
        for item in data.data_trust
    )


def test_map_summary_data_trust_check_labels_follow_lang_for_same_summary_data() -> None:
    base_summary = minimal_summary(
        run_suitability=[
            {
                "check": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "pass",
                "explanation": "Wide enough speed sweep for order tracking.",
            },
        ],
    )

    summary_en = {**base_summary, "lang": "en"}
    summary_nl = {**base_summary, "lang": "nl"}

    data_en = map_summary(summary_en)
    data_nl = map_summary(summary_nl)

    assert data_en.data_trust[0].check == "Speed variation"
    assert data_nl.data_trust[0].check == "Snelheidsvariatie"


def test_map_summary_certainty_reason_ignores_unrelated_reference_gap() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        top_causes=[
            {
                "suspected_source": "wheel/tire",
                "strongest_location": "Front Left",
                "strongest_speed_band": "60-80 km/h",
                "confidence": 0.82,
            },
        ],
        findings=[{"finding_id": "REF_ENGINE"}],
    )
    data = map_summary(summary)
    assert data.observed.certainty_reason
    assert "Missing reference data" not in data.observed.certainty_reason


def test_map_summary_certainty_reason_keeps_relevant_reference_gap() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        top_causes=[
            {
                "finding_id": "F_ENGINE",
                "suspected_source": "engine",
                "strongest_location": "Engine Bay",
                "strongest_speed_band": "60-80 km/h",
                "confidence": 0.82,
            },
        ],
        findings=[{"finding_id": "REF_ENGINE"}],
    )
    data = map_summary(summary)
    assert data.observed.certainty_reason == "Missing reference data limits pattern matching"
