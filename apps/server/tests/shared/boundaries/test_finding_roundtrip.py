"""Roundtrip test: Finding → FindingPayload → Finding is lossless."""

from __future__ import annotations

import pytest

from vibesensor.domain.finding import Finding, FindingKind, VibrationSource
from vibesensor.domain.finding_evidence import FindingEvidence
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.domain.signature import Signature
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.finding import finding_from_payload, finding_payload_from_domain


def _roundtrip(finding: Finding) -> Finding:
    """Serialize then deserialize a Finding."""
    payload = finding_payload_from_domain(finding)
    return finding_from_payload(payload)


class TestFindingRoundtrip:
    """Finding → FindingPayload → Finding preserves domain-relevant fields."""

    def test_minimal_finding(self) -> None:
        original = Finding(finding_id="F001", suspected_source=VibrationSource.WHEEL_TIRE)
        restored = _roundtrip(original)
        assert restored.finding_id == original.finding_id
        assert restored.suspected_source is original.suspected_source
        assert restored.kind is FindingKind.DIAGNOSTIC

    def test_finding_key_preserved(self) -> None:
        original = Finding(
            finding_id="F001",
            finding_key="wheel_1x",
            suspected_source=VibrationSource.WHEEL_TIRE,
        )
        restored = _roundtrip(original)
        assert restored.finding_key == "wheel_1x"

    def test_scalar_fields_preserved(self) -> None:
        original = Finding(
            finding_id="F002",
            finding_key="peak_200hz",
            suspected_source=VibrationSource.DRIVELINE,
            confidence=0.85,
            frequency_hz=200.0,
            order="2x driveshaft",
            severity="diagnostic",
            strongest_location="rear-left",
            strongest_speed_band="80-100 km/h",
            peak_classification="harmonic",
            ranking_score=3.5,
            dominance_ratio=2.1,
            diffuse_excitation=True,
            weak_spatial_separation=True,
            vibration_strength_db=22.3,
            cruise_fraction=0.6,
        )
        restored = _roundtrip(original)
        assert restored.finding_id == original.finding_id
        assert restored.finding_key == original.finding_key
        assert restored.suspected_source is original.suspected_source
        assert restored.confidence == pytest.approx(original.confidence)
        assert restored.frequency_hz == pytest.approx(original.frequency_hz)
        assert restored.order == original.order
        assert restored.severity == original.severity
        assert restored.strongest_location == original.strongest_location
        assert restored.strongest_speed_band == original.strongest_speed_band
        assert restored.peak_classification == original.peak_classification
        assert restored.ranking_score == pytest.approx(original.ranking_score)
        assert restored.dominance_ratio == pytest.approx(original.dominance_ratio)
        assert restored.diffuse_excitation is True
        assert restored.weak_spatial_separation is True
        assert restored.vibration_strength_db == pytest.approx(original.vibration_strength_db)
        assert restored.cruise_fraction == pytest.approx(original.cruise_fraction)

    def test_evidence_preserved(self) -> None:
        evidence = FindingEvidence(
            match_rate=0.8,
            presence_ratio=0.9,
            burstiness=0.1,
            spatial_concentration=0.7,
            frequency_correlation=0.6,
            speed_uniformity=0.5,
            spatial_uniformity=0.4,
            snr_db=15.0,
            vibration_strength_db=20.0,
        )
        original = Finding(
            finding_id="F003",
            suspected_source=VibrationSource.WHEEL_TIRE,
            evidence=evidence,
        )
        restored = _roundtrip(original)
        assert restored.evidence is not None
        assert restored.evidence.match_rate == pytest.approx(0.8)
        assert restored.evidence.snr_db == pytest.approx(15.0)
        assert restored.evidence.vibration_strength_db == pytest.approx(20.0)

    def test_location_hotspot_preserved(self) -> None:
        location = LocationHotspot(
            strongest_location="front-left",
            dominance_ratio=2.5,
            localization_confidence=0.9,
            weak_spatial_separation=False,
            ambiguous=True,
            alternative_locations=("front-right",),
            location_count=2,
        )
        original = Finding(
            finding_id="F004",
            suspected_source=VibrationSource.WHEEL_TIRE,
            location=location,
        )
        restored = _roundtrip(original)
        assert restored.location is not None
        assert restored.location.strongest_location == "front-left"
        assert restored.location.dominance_ratio == pytest.approx(2.5)
        assert restored.location.alternative_locations == ("front-right",)

    def test_signatures_preserved(self) -> None:
        sigs = (
            Signature.from_label("1x wheel", source=VibrationSource.WHEEL_TIRE, support_score=0.8),
            Signature.from_label("harmonic", source=VibrationSource.WHEEL_TIRE, support_score=0.5),
        )
        original = Finding(
            finding_id="F005",
            suspected_source=VibrationSource.WHEEL_TIRE,
            confidence=0.7,
            signatures=sigs,
        )
        restored = _roundtrip(original)
        assert len(restored.signatures) == 2
        assert restored.signature_labels == original.signature_labels

    def test_reference_finding_kind_preserved(self) -> None:
        original = Finding(finding_id="REF_SPEED", severity="reference")
        restored = _roundtrip(original)
        assert restored.kind is FindingKind.REFERENCE

    def test_informational_finding_kind_preserved(self) -> None:
        original = Finding(finding_id="F_INFO", severity="info")
        restored = _roundtrip(original)
        assert restored.kind is FindingKind.INFORMATIONAL

    def test_origin_reason_preserved(self) -> None:
        origin = VibrationOrigin(
            suspected_source=VibrationSource.WHEEL_TIRE,
            reason="Strong 1x wheel order detected",
        )
        original = Finding(
            finding_id="F006",
            suspected_source=VibrationSource.WHEEL_TIRE,
            origin=origin,
        )
        restored = _roundtrip(original)
        assert restored.origin is not None
        assert restored.origin.reason == "Strong 1x wheel order detected"
