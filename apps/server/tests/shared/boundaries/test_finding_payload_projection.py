"""Tests for projecting domain findings into the canonical boundary payload shape."""

from __future__ import annotations

from vibesensor.domain import Finding, FindingEvidence, OrderMatchObservation, VibrationSource
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.summary_fields.finding import finding_payload_from_domain


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


def test_projection_keeps_strength_metric_when_evidence_exists_without_nested_strength() -> None:
    payload = finding_payload_from_domain(
        Finding(
            finding_id="F001",
            suspected_source=VibrationSource.WHEEL_TIRE,
            vibration_strength_db=22.3,
            evidence=FindingEvidence(
                match_rate=0.8,
                presence_ratio=0.9,
                burstiness=0.1,
                spatial_concentration=0.7,
                frequency_correlation=0.6,
                speed_uniformity=0.5,
                spatial_uniformity=0.4,
                snr_db=15.0,
            ),
        )
    )

    assert payload["amplitude_metric"]["value"] == 22.3
    assert payload["evidence_metrics"]["vibration_strength_db"] == 22.3


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


def test_projection_emits_frequency_hz_in_canonical_payload() -> None:
    payload = finding_payload_from_domain(
        Finding(
            finding_id="F_HZ",
            suspected_source=VibrationSource.WHEEL_TIRE,
            frequency_hz=41.0,
        )
    )

    assert payload["frequency_hz"] == 41.0


def test_projection_keeps_canonical_domain_and_presentation_fields_together() -> None:
    finding = Finding(
        finding_id="F_ORDER",
        suspected_source=VibrationSource.WHEEL_TIRE,
        confidence=0.82,
        strongest_location="rear-right",
        strongest_speed_band="80-100 km/h",
        dominance_ratio=3.1,
        vibration_strength_db=22.3,
        origin=VibrationOrigin.from_analysis_inputs(
            suspected_source=VibrationSource.WHEEL_TIRE,
            dominance_ratio=3.1,
            speed_band="80-100 km/h",
            dominant_phase="cruise",
            reason="Strong wheel-order correlation",
        ),
    ).with_confidence_assessment(
        strength_band_key="moderate",
        steady_speed=True,
        has_reference_gaps=False,
        sensor_count=2,
    )

    payload = finding_payload_from_domain(finding)

    assert payload["finding_id"] == "F_ORDER"
    assert payload["strongest_location"] == "rear-right"
    assert payload["evidence_summary"] == "Strong wheel-order correlation"
    assert payload["confidence_tone"] == finding.confidence_assessment.tone
    assert payload["amplitude_metric"]["value"] == 22.3
    assert payload["frequency_hz_or_order"] == ""


def test_projection_keeps_empty_signatures_list_for_contract_stability() -> None:
    payload = finding_payload_from_domain(
        Finding(
            finding_id="F_NO_SIGS",
            suspected_source=VibrationSource.WHEEL_TIRE,
        )
    )

    assert payload["signatures_observed"] == []
