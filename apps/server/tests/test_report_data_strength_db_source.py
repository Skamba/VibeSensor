from __future__ import annotations

from vibesensor_core.vibration_strength import vibration_strength_db_scalar

from vibesensor.report.report_data import map_summary


def _summary_with_top_order(finding: dict, *, sensor_rows: list[dict] | None = None) -> dict:
    return {
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
        "findings": [finding],
        "sensor_intensity_by_location": sensor_rows or [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }


def test_map_summary_strength_label_uses_finding_db_when_sensor_rows_missing() -> None:
    summary = _summary_with_top_order(
        {
            "finding_id": "F_ORDER",
            "amplitude_metric": {"value": 0.015, "units": "g"},
            "evidence_metrics": {"vibration_strength_db": 23.4},
        }
    )

    data = map_summary(summary)

    assert data.observed.strength_label is not None
    assert "23.4 dB" in data.observed.strength_label
    assert "0.015 g peak" in data.observed.strength_label


def test_map_summary_strength_label_derives_db_from_finding_amp_and_floor() -> None:
    amp = 0.015
    floor = 0.005
    expected_db = vibration_strength_db_scalar(peak_band_rms_amp_g=amp, floor_amp_g=floor)
    summary = _summary_with_top_order(
        {
            "finding_id": "F_ORDER",
            "amplitude_metric": {"value": amp, "units": "g"},
            "evidence_metrics": {"mean_noise_floor": floor},
        }
    )

    data = map_summary(summary)

    assert data.observed.strength_label is not None
    assert f"{expected_db:.1f} dB" in data.observed.strength_label
    assert "0.015 g peak" in data.observed.strength_label


def test_map_summary_prefers_non_ref_top_cause_for_observed_location() -> None:
    summary = _summary_with_top_order(
        {
            "finding_id": "F_ORDER",
            "amplitude_metric": {"value": 0.015, "units": "g"},
            "evidence_metrics": {"vibration_strength_db": 23.4},
        }
    )
    summary["top_causes"] = [
        {
            "finding_id": "REF_GAP_1",
            "suspected_source": "unknown_resonance",
            "strongest_location": "unknown",
            "strongest_speed_band": "100-110 km/h",
            "confidence_0_to_1": 0.95,
            "signatures_observed": ["reference gap"],
        },
        {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
            "strongest_location": "rear-left",
            "strongest_speed_band": "40-60 km/h",
            "confidence_0_to_1": 0.8,
            "signatures_observed": ["1x wheel order"],
        },
    ]

    data = map_summary(summary)

    assert data.observed.strongest_sensor_location.lower() == "rear-left"


def test_map_summary_falls_back_to_actionable_findings_when_top_cause_is_placeholder() -> None:
    summary = _summary_with_top_order(
        {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
            "strongest_location": "rear-left",
            "strongest_speed_band": "40-60 km/h",
            "amplitude_metric": {"value": 0.015, "units": "g"},
            "evidence_metrics": {"vibration_strength_db": 23.4},
        }
    )
    summary["top_causes"] = [
        {
            "source": "unknown_resonance",
            "strongest_location": "unknown",
            "strongest_speed_band": "100-110 km/h",
            "confidence_0_to_1": 0.95,
        }
    ]

    data = map_summary(summary)

    assert data.observed.strongest_sensor_location.lower() == "rear-left"


def test_map_summary_pattern_evidence_uses_same_primary_candidate_as_observed() -> None:
    summary = _summary_with_top_order(
        {
            "finding_id": "F_ORDER",
            "source": "wheel/tire",
            "strongest_location": "rear-left",
            "strongest_speed_band": "40-60 km/h",
            "signatures_observed": ["1x wheel order"],
            "amplitude_metric": {"value": 0.015, "units": "g"},
            "evidence_metrics": {"vibration_strength_db": 23.4},
        }
    )
    summary["top_causes"] = [
        {
            "source": "unknown_resonance",
            "strongest_location": "unknown",
            "strongest_speed_band": "100-110 km/h",
            "confidence_0_to_1": 0.95,
            "weak_spatial_separation": False,
            "signatures_observed": ["reference gap"],
        }
    ]

    data = map_summary(summary)

    assert data.observed.strongest_sensor_location.lower() == "rear-left"
    assert data.observed.speed_band == "40-60 km/h"
    assert data.pattern_evidence.strongest_location.lower() == "rear-left"
    assert data.pattern_evidence.speed_band == "40-60 km/h"
    assert data.pattern_evidence.why_parts_text is not None
    assert "wheel" in data.pattern_evidence.why_parts_text.lower()


def test_map_summary_peak_rows_render_missing_values_as_dashes() -> None:
    summary = {
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {
            "peaks_table": [
                {
                    "order_label": "",
                    "peak_classification": "persistent",
                    "typical_speed_band": "any",
                }
            ]
        },
    }

    data = map_summary(summary)

    assert data.peak_rows
    row = data.peak_rows[0]
    assert row.rank == "—"
    assert row.freq_hz == "—"
    assert row.amp_g == "—"


def test_map_summary_peak_rows_use_source_hint_for_system_label() -> None:
    summary = {
        "lang": "en",
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
                    "p95_amp_g": 0.12,
                    "strength_db": 18.4,
                    "presence_ratio": 0.85,
                    "persistence_score": 0.0867,
                    "peak_classification": "patterned",
                    "source": "wheel/tire",
                    "typical_speed_band": "60-80 km/h",
                }
            ]
        },
    }

    data = map_summary(summary)

    assert data.peak_rows
    assert data.peak_rows[0].system == "Wheel / Tire"
