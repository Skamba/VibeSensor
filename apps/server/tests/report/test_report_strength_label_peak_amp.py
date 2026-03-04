from __future__ import annotations

from typing import Any

from vibesensor_core.vibration_strength import vibration_strength_db_scalar

from vibesensor.analysis.report_data_builder import map_summary
from vibesensor.analysis.strength_labels import strength_text
from vibesensor.report.pdf_builder import _strength_with_peak

# ---------------------------------------------------------------------------
# Shared top-cause / finding templates
# ---------------------------------------------------------------------------

_F_ORDER_CAUSE: dict[str, Any] = {
    "finding_id": "F_ORDER",
    "suspected_source": "wheel/tire",
    "strongest_location": "front-left",
    "strongest_speed_band": "40-60 km/h",
    "confidence_0_to_1": 0.8,
    "signatures_observed": ["1x wheel order"],
}


def _make_summary(
    *,
    top_causes: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    sensor_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a summary dict with sensible defaults for the unchanging keys."""
    return {
        "top_causes": top_causes or [],
        "findings": findings or [],
        "sensor_intensity_by_location": sensor_rows or [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }


def test_strength_text_value_with_peak_amp() -> None:
    txt = strength_text(22.0, lang="en")
    assert "Moderate" in txt
    assert "22.0 dB" in txt
    assert " g" not in txt


def test_map_summary_strength_label_includes_peak_amp_when_available() -> None:
    summary = _make_summary(
        top_causes=[_F_ORDER_CAUSE],
        findings=[
            {
                "finding_id": "F_ORDER",
                "amplitude_metric": {"value": 0.032, "units": "g"},
            }
        ],
        sensor_rows=[{"p95_intensity_db": 22.0}],
    )
    data = map_summary(summary)
    assert data.observed.strength_label is not None
    assert "22.0 dB" in data.observed.strength_label
    assert " g" not in data.observed.strength_label
    assert data.observed.strength_peak_db == 22.0
    assert data.pattern_evidence.strength_label is not None
    assert " g" not in data.pattern_evidence.strength_label
    assert data.pattern_evidence.strength_peak_db == 22.0


def test_map_summary_strength_label_falls_back_to_db_only_without_peak_amp() -> None:
    summary = _make_summary(sensor_rows=[{"p95_intensity_db": 22.0}])
    data = map_summary(summary)
    assert data.observed.strength_label is not None
    assert "22.0 dB" in data.observed.strength_label
    assert "g peak" not in data.observed.strength_label
    assert data.observed.strength_peak_db == 22.0
    assert data.pattern_evidence.strength_peak_db == 22.0


def test_strength_with_peak_appends_only_when_label_lacks_db_text() -> None:
    # Label already contains "dB" → peak suffix should NOT be appended (avoids duplication)
    assert _strength_with_peak("Moderate (22.0 dB)", 0.032, fallback="N/A") == "Moderate (22.0 dB)"
    assert (
        _strength_with_peak("Moderate (22.0 dB · 0.0 dB peak)", 0.032, fallback="N/A")
        == "Moderate (22.0 dB · 0.0 dB peak)"
    )
    # Label without "dB" → peak suffix should be appended
    assert _strength_with_peak("Moderate", 15.3, fallback="N/A") == "Moderate · 15.3 dB peak"


def test_map_summary_strength_label_uses_finding_db_when_sensor_rows_missing() -> None:
    summary = _make_summary(
        top_causes=[_F_ORDER_CAUSE],
        findings=[
            {
                "finding_id": "F_ORDER",
                "amplitude_metric": {"value": 0.015, "units": "g"},
                "evidence_metrics": {"vibration_strength_db": 23.4},
            }
        ],
    )
    data = map_summary(summary)
    assert data.observed.strength_label is not None
    assert "23.4 dB" in data.observed.strength_label
    assert " g" not in data.observed.strength_label
    assert data.observed.strength_peak_db == 23.4


def test_map_summary_strength_label_derives_db_from_finding_amp_and_floor() -> None:
    amp = 0.015
    floor = 0.005
    expected_db = vibration_strength_db_scalar(peak_band_rms_amp_g=amp, floor_amp_g=floor)
    summary = _make_summary(
        top_causes=[_F_ORDER_CAUSE],
        findings=[
            {
                "finding_id": "F_ORDER",
                "amplitude_metric": {"value": amp, "units": "g"},
                "evidence_metrics": {"mean_noise_floor": floor},
            }
        ],
    )
    data = map_summary(summary)
    assert data.observed.strength_label is not None
    assert f"{expected_db:.1f} dB" in data.observed.strength_label
    assert " g" not in data.observed.strength_label
    assert data.observed.strength_peak_db is not None


def test_map_summary_strength_label_keeps_db_and_peak_from_same_finding() -> None:
    summary = _make_summary(
        top_causes=[{"finding_id": "F_PRIMARY"}, {"finding_id": "F_SECONDARY"}],
        findings=[
            {
                "finding_id": "F_PRIMARY",
                "amplitude_metric": {"value": 0.011, "units": "g"},
            },
            {
                "finding_id": "F_SECONDARY",
                "evidence_metrics": {"vibration_strength_db": 40.0},
            },
        ],
        sensor_rows=[{"p95_intensity_db": 22.0}],
    )
    data = map_summary(summary)
    assert data.observed.strength_label is not None
    assert "40.0 dB" in data.observed.strength_label
    assert "g peak" not in data.observed.strength_label


def test_map_summary_strength_label_uses_strongest_sensor_row_when_unsorted() -> None:
    summary = _make_summary(
        sensor_rows=[
            {"location": "A", "p95_intensity_db": 12.0},
            {"location": "B", "p95_intensity_db": 28.0},
            {"location": "C", "p95_intensity_db": 20.0},
        ],
    )
    data = map_summary(summary)
    assert data.observed.strength_label is not None
    assert "28.0 dB" in data.observed.strength_label
