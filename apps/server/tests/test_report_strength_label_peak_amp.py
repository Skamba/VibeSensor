from __future__ import annotations

from vibesensor.report.report_data import map_summary
from vibesensor.report.strength_labels import strength_text


def test_strength_text_value_with_peak_amp() -> None:
    txt = strength_text(22.0, lang="en", peak_amp_g=0.032)
    assert "Moderate" in txt
    assert "22.0 dB" in txt
    assert "0.032 g peak" in txt


def test_map_summary_strength_label_includes_peak_amp_when_available() -> None:
    summary: dict = {
        "top_causes": [
            {
                "finding_id": "F_ORDER",
                "suspected_source": "wheel/tire",
                "strongest_location": "front-left",
                "strongest_speed_band": "40-60 km/h",
                "confidence_0_to_1": 0.8,
                "signatures_observed": ["1x wheel order"],
            }
        ],
        "findings": [
            {
                "finding_id": "F_ORDER",
                "amplitude_metric": {"value": 0.032, "units": "g"},
            }
        ],
        "sensor_intensity_by_location": [{"p95_intensity_db": 22.0}],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }
    data = map_summary(summary)
    assert data.observed.strength_label is not None
    assert "22.0 dB" in data.observed.strength_label
    assert "0.032 g peak" in data.observed.strength_label
    assert data.pattern_evidence.strength_label is not None
    assert "0.032 g peak" in data.pattern_evidence.strength_label


def test_map_summary_strength_label_falls_back_to_db_only_without_peak_amp() -> None:
    summary: dict = {
        "top_causes": [],
        "findings": [],
        "sensor_intensity_by_location": [{"p95_intensity_db": 22.0}],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }
    data = map_summary(summary)
    assert data.observed.strength_label is not None
    assert "22.0 dB" in data.observed.strength_label
    assert "g peak" not in data.observed.strength_label
