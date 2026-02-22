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
