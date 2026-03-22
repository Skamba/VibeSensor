from __future__ import annotations

from vibesensor.domain import Finding, OrderMatchObservation, VibrationSource
from vibesensor.shared.boundaries.finding import finding_payload_from_domain


def test_projection_emits_canonical_amplitude_metric_shape() -> None:
    payload = finding_payload_from_domain(
        Finding(
            finding_id="F001",
            suspected_source=VibrationSource.WHEEL_TIRE,
            vibration_strength_db=22.3,
        )
    )

    assert payload["amplitude_metric"] == {
        "name": "vibration_strength_db",
        "value": 22.3,
        "units": "dB",
        "definition": {"_i18n_key": "METRIC_VIBRATION_STRENGTH_DB"},
    }
    assert payload["evidence_metrics"] == {"vibration_strength_db": 22.3}


def test_projection_omits_removed_dead_contract_fields() -> None:
    payload = finding_payload_from_domain(
        Finding(
            finding_id="F001",
            suspected_source=VibrationSource.WHEEL_TIRE,
            vibration_strength_db=22.3,
        )
    )

    assert {
        "quick_checks",
        "peak_speed_kmh",
        "speed_window_kmh",
        "localization_confidence",
        "corroborating_locations",
        "next_sensor_move",
        "actions",
        "phase_presence",
        "grouped_count",
        "diagnostic_caveat",
    }.isdisjoint(payload)


def test_projection_serializes_matched_points_with_boundary_shape() -> None:
    payload = finding_payload_from_domain(
        Finding(
            finding_id="F001",
            suspected_source=VibrationSource.WHEEL_TIRE,
            matched_points=(
                OrderMatchObservation(
                    t_s=1.5,
                    speed_kmh=62.0,
                    predicted_hz=11.2,
                    matched_hz=11.4,
                    rel_error=0.018,
                    amp=0.42,
                    location="front-left",
                    phase="cruise",
                ),
            ),
        )
    )

    assert payload["matched_points"] == [
        {
            "t_s": 1.5,
            "speed_kmh": 62.0,
            "predicted_hz": 11.2,
            "matched_hz": 11.4,
            "rel_error": 0.018,
            "amp": 0.42,
            "location": "front-left",
            "phase": "cruise",
        }
    ]
