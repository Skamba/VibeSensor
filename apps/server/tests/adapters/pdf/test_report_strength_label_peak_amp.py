"""Tests for report strength-label text and peak-dB presentation behavior."""

from __future__ import annotations

import pytest
from test_support.report_helpers import minimal_summary

from vibesensor.shared.boundaries.reporting.preparation import prepare_report_input
from vibesensor.shared.report_presentation import strength_text
from vibesensor.use_cases.history.report_document.builder import build_report_document

# ---------------------------------------------------------------------------
# Shared top-cause / finding templates
# ---------------------------------------------------------------------------

_F_ORDER_CAUSE: dict[str, object] = {
    "finding_id": "F_ORDER",
    "suspected_source": "wheel/tire",
    "strongest_location": "front-left",
    "strongest_speed_band": "40-60 km/h",
    "confidence": 0.8,
    "signatures_observed": ["1x wheel order"],
}


def test_strength_text_value_with_peak_amp() -> None:
    txt = strength_text(22.0, lang="en")
    assert "Moderate" in txt
    assert "22.0 dB" in txt
    assert " g" not in txt


@pytest.mark.parametrize(
    ("summary_overrides", "expected_db"),
    [
        pytest.param(
            {
                "top_causes": [_F_ORDER_CAUSE],
                "findings": [
                    {"finding_id": "F_ORDER", "amplitude_metric": {"value": 0.032, "units": "g"}},
                ],
                "sensor_intensity_by_location": [{"p95_intensity_db": 22.0}],
            },
            22.0,
            id="sensor-db-ignores-peak-amp",
        ),
        pytest.param(
            {"sensor_intensity_by_location": [{"p95_intensity_db": 22.0}]},
            22.0,
            id="sensor-db-without-findings",
        ),
        pytest.param(
            {
                "top_causes": [_F_ORDER_CAUSE],
                "findings": [
                    {
                        "finding_id": "F_ORDER",
                        "amplitude_metric": {"value": 0.015, "units": "g"},
                        "evidence_metrics": {"vibration_strength_db": 23.4},
                    },
                ],
            },
            23.4,
            id="finding-db-when-sensor-rows-missing",
        ),
        pytest.param(
            {
                "top_causes": [{"finding_id": "F_PRIMARY"}, {"finding_id": "F_SECONDARY"}],
                "findings": [
                    {"finding_id": "F_PRIMARY", "amplitude_metric": {"value": 0.011, "units": "g"}},
                    {
                        "finding_id": "F_SECONDARY",
                        "evidence_metrics": {"vibration_strength_db": 40.0},
                    },
                ],
                "sensor_intensity_by_location": [{"p95_intensity_db": 22.0}],
            },
            40.0,
            id="db-and-peak-from-same-finding",
        ),
        pytest.param(
            {
                "sensor_intensity_by_location": [
                    {"location": "A", "p95_intensity_db": 12.0},
                    {"location": "B", "p95_intensity_db": 28.0},
                    {"location": "C", "p95_intensity_db": 20.0},
                ],
            },
            28.0,
            id="strongest-unsorted-sensor-row",
        ),
    ],
)
def test_build_report_document_strength_label_uses_db_source(
    summary_overrides: dict[str, object],
    expected_db: float,
) -> None:
    data = build_report_document(prepare_report_input(minimal_summary(**summary_overrides)))

    label = data.observed.strength_label
    assert label is not None
    assert f"{expected_db:.1f} dB" in label
    assert " g" not in label
    assert "g peak" not in label
    assert data.observed.strength_peak_db == expected_db
    assert data.pattern_evidence.strength_peak_db == expected_db
    assert " g" not in (data.pattern_evidence.strength_label or "")
