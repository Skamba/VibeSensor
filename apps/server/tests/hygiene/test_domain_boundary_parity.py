"""Behavior checks for domain-to-boundary payload codecs."""

from __future__ import annotations

from pydantic import TypeAdapter

from vibesensor.domain import (
    ConfidenceAssessment,
    Finding,
    FindingEvidence,
    RunSuitability,
    Signature,
    SuitabilityCheck,
    VibrationSource,
)
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.runs.suitability import (
    run_suitability_from_payload,
    run_suitability_payload,
)
from vibesensor.shared.boundaries.summary_fields.finding import (
    finding_from_payload,
    finding_payload_from_domain,
)
from vibesensor.shared.types.history_analysis_contracts import (
    FindingPayload,
    RunSuitabilityCheck,
)


def test_finding_payload_round_trips_domain_summary_boundary() -> None:
    """Finding codec owns rich domain-to-public payload field mapping."""

    location = LocationHotspot(
        strongest_location="front_left_wheel",
        dominance_ratio=1.8,
        localization_confidence=0.74,
        weak_spatial_separation=True,
        ambiguous=True,
        alternative_locations=("front_right_wheel",),
        location_count=4,
    )
    finding = Finding(
        finding_id="FIND-WHEEL-1",
        finding_key="wheel_order",
        suspected_source=VibrationSource.WHEEL_TIRE,
        confidence=0.82,
        frequency_hz=43.5,
        order="1.0x wheel",
        severity="warn",
        strongest_location="front_left_wheel",
        strongest_speed_band="80-90 km/h",
        peak_classification="wheel_order",
        dominant_phase="cruise",
        ranking_score=0.91,
        dominance_ratio=1.8,
        diffuse_excitation=False,
        weak_spatial_separation=True,
        vibration_strength_db=16.4,
        cruise_fraction=0.67,
        phases_detected=("acceleration", "cruise"),
        matched_points=(
            OrderMatchObservation(
                predicted_hz=42.0,
                matched_hz=43.5,
                rel_error=0.035,
                amp=0.18,
                location="front_left_wheel",
                t_s=12.5,
                speed_kmh=86.0,
                phase="cruise",
            ),
        ),
        evidence=FindingEvidence(
            match_rate=0.76,
            global_match_rate=0.61,
            focused_speed_band="80-90 km/h",
            mean_relative_error=0.034,
            mean_noise_floor_db=-48.0,
            possible_samples=28,
            matched_samples=22,
            snr_db=9.5,
            presence_ratio=0.72,
            burstiness=0.12,
            spatial_concentration=0.86,
            frequency_correlation=0.8,
            speed_uniformity=0.78,
            spatial_uniformity=0.69,
            phases_with_evidence=2,
            phase_confidences=(("acceleration", 0.71), ("cruise", 0.86)),
            vibration_strength_db=16.4,
        ),
        location=location,
        confidence_assessment=ConfidenceAssessment(
            raw_confidence=0.82,
            label_key="CONFIDENCE_HIGH",
            tone="success",
            pct_text="82%",
            reason="clear repeated order support",
            weak_spatial=True,
        ),
        origin=VibrationOrigin.from_analysis_inputs(
            suspected_source=VibrationSource.WHEEL_TIRE,
            hotspot=location,
            dominance_ratio=1.8,
            speed_band="80-90 km/h",
            dominant_phase="cruise",
            reason="wheel order dominates the cruise band",
        ),
        signatures=(
            Signature.from_label(
                "wheel order",
                source=VibrationSource.WHEEL_TIRE,
                support_score=0.82,
            ),
        ),
    )

    payload = TypeAdapter(FindingPayload).validate_python(finding_payload_from_domain(finding))
    decoded = finding_from_payload(payload)

    assert payload["finding_id"] == finding.finding_id
    assert payload["suspected_source"] == "wheel/tire"
    assert "source" not in payload
    assert payload["evidence_metrics"]["vibration_strength_db"] == 16.4
    assert payload["evidence_metrics"]["matched_samples"] == 22
    assert payload["location_hotspot"]["ambiguous_locations"] == ["front_right_wheel"]
    assert payload["location_hotspot"]["location_count"] == 4
    assert payload["matched_points"][0]["matched_hz"] == 43.5
    assert payload["matched_points"][0]["phase"] == "cruise"
    assert payload["phase_evidence"]["phases_detected"] == ["acceleration", "cruise"]
    assert payload["confidence_label_key"] == "CONFIDENCE_HIGH"
    assert payload["signatures_observed"] == ["wheel order"]
    assert decoded == finding


def test_run_suitability_payload_round_trips_domain_boundary() -> None:
    """Run suitability codecs own check-key/detail translation."""

    suitability = RunSuitability(
        checks=(
            SuitabilityCheck(
                check_key="SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                state="warn",
                details=(("sat_count", 3),),
            ),
        ),
    )

    payload = TypeAdapter(list[RunSuitabilityCheck]).validate_python(
        run_suitability_payload(suitability)
    )
    decoded = run_suitability_from_payload(payload)

    assert payload == [
        {
            "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            "state": "warn",
            "explanation": {
                "_i18n_key": "SUITABILITY_SATURATION_WARN",
                "sat_count": 3,
            },
        }
    ]
    assert decoded == suitability
    assert decoded.checks[0].details == (("sat_count", 3),)
