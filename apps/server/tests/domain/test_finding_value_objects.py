from __future__ import annotations

import pytest

from vibesensor.domain import ConfidenceAssessment, Finding, FindingEvidence, LocationHotspot
from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload


class TestFindingDomainObject:
    """Finding domain object, distinct from the TypedDict payload."""

    @pytest.mark.parametrize(
        (
            "finding",
            "expected_is_diagnostic",
            "expected_is_reference",
            "expected_is_info",
            "expected_confidence_pct",
        ),
        [
            pytest.param(
                Finding(
                    finding_id="F001",
                    suspected_source="wheel/tire",
                    confidence=0.85,
                    severity="high",
                ),
                True,
                False,
                False,
                85,
                id="diagnostic-finding",
            ),
            pytest.param(
                Finding(finding_id="REF_SPEED"),
                False,
                True,
                False,
                None,
                id="reference-finding",
            ),
            pytest.param(
                Finding(finding_id="F010", severity="info"),
                False,
                False,
                True,
                None,
                id="informational-finding",
            ),
        ],
    )
    def test_finding_kind_cases(
        self,
        finding: Finding,
        expected_is_diagnostic: bool,
        expected_is_reference: bool,
        expected_is_info: bool,
        expected_confidence_pct: int | None,
    ) -> None:
        assert finding.is_diagnostic is expected_is_diagnostic
        assert finding.is_reference is expected_is_reference
        assert finding.is_informational is expected_is_info
        assert finding.confidence_pct == expected_confidence_pct

    def test_source_normalized(self) -> None:
        finding = Finding(suspected_source=" Wheel/Tire ")
        assert finding.source_normalized == "wheel/tire"

    def test_ref_prefix_override_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        payload: dict[str, object] = {
            "finding_id": "REF_SPEED",
            "suspected_source": "engine",
            "finding_kind": "diagnostic",
        }

        finding = finding_from_payload(payload)

        assert finding.is_diagnostic
        assert "REF_ prefix" in caplog.text

    def test_from_payload(self) -> None:
        payload: dict[str, object] = {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.85,
            "frequency_hz": 42.5,
            "order": "1x",
            "severity": "high",
            "strongest_location": "FL",
            "strongest_speed_band": "80-100 km/h",
            "peak_classification": "harmonic",
            "evidence_summary": "some evidence",
            "legacy_unused_field": [],
        }

        finding = finding_from_payload(payload)

        assert finding.finding_id == "F001"
        assert finding.suspected_source == "wheel/tire"
        assert finding.confidence == 0.85
        assert finding.frequency_hz == 42.5
        assert finding.order == "1x"
        assert finding.severity == "high"
        assert finding.strongest_location == "FL"
        assert finding.strongest_speed_band == "80-100 km/h"
        assert finding.peaks.classification == "harmonic"
        assert finding.is_diagnostic
        assert finding.confidence_pct == 85

    def test_from_payload_minimal(self) -> None:
        finding = finding_from_payload({"finding_id": "F001", "suspected_source": "engine"})
        assert finding.finding_id == "F001"
        assert finding.suspected_source == "engine"
        assert finding.confidence is None
        assert finding.frequency_hz is None

    def test_from_payload_reference(self) -> None:
        finding = finding_from_payload({"finding_id": "REF_SPEED", "suspected_source": ""})
        assert finding.is_reference
        assert not finding.is_diagnostic


class TestFindingComposition:
    def test_finding_with_evidence(self) -> None:
        evidence = FindingEvidence(match_rate=0.9, snr_db=15.0)
        finding = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            confidence=0.85,
            evidence=evidence,
        )

        assert finding.evidence is not None
        assert finding.evidence.is_strong
        assert finding.evidence.match_rate == 0.9

    def test_finding_with_location(self) -> None:
        location = LocationHotspot(
            strongest_location="FL wheel",
            dominance_ratio=0.8,
        )
        finding = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            confidence=0.85,
            location=location,
        )

        assert finding.location is not None
        assert finding.location.is_well_localized
        assert finding.location.display_location == "Fl Wheel"

    def test_finding_with_confidence_assessment(self) -> None:
        assessment = ConfidenceAssessment.assess(0.85)
        finding = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            confidence=0.85,
            confidence_assessment=assessment,
        )

        assert finding.confidence_assessment is not None
        assert finding.confidence_assessment.tier == "C"
        assert finding.confidence_assessment.is_conclusive

    def test_finding_from_payload_extracts_evidence(self) -> None:
        finding = finding_from_payload(
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.85,
                "evidence_metrics": {
                    "match_rate": 0.9,
                    "snr_db": 15.0,
                    "presence_ratio": 0.7,
                    "vibration_strength_db": 25.3,
                },
            }
        )

        assert finding.evidence is not None
        assert finding.evidence.match_rate == 0.9
        assert finding.evidence.snr_db == 15.0
        assert finding.evidence.vibration_strength_db == 25.3
        assert finding.vibration_strength_db == 25.3

    def test_finding_from_payload_extracts_location(self) -> None:
        finding = finding_from_payload(
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.85,
                "location_hotspot": {
                    "top_location": "FL wheel",
                    "dominance_ratio": 0.75,
                    "weak_spatial_separation": False,
                },
            }
        )

        assert finding.location is not None
        assert finding.location.strongest_location == "FL wheel"
        assert finding.location.dominance_ratio == 0.75

    def test_finding_from_payload_preserves_top_location_identity(self) -> None:
        finding = finding_from_payload(
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.85,
                "location_hotspot": {
                    "location": "ambiguous location: Front Left / Front Right",
                    "top_location": "Front Left",
                    "ambiguous_location": True,
                    "ambiguous_locations": ["Front Left", "Front Right"],
                    "weak_spatial_separation": True,
                },
            }
        )

        assert finding.location is not None
        assert finding.location.strongest_location == "Front Left"
        assert not finding.location.is_actionable

    def test_finding_from_payload_no_evidence(self) -> None:
        finding = finding_from_payload({"finding_id": "REF_SPEED", "severity": "reference"})
        assert finding.evidence is None
        assert finding.location is None

    def test_finding_from_payload_populates_origin_and_signatures(self) -> None:
        finding = finding_from_payload(
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.85,
                "strongest_speed_band": "80-90 km/h",
                "signatures_observed": ["1x wheel order", "2x wheel order"],
                "location_hotspot": {"top_location": "FL wheel", "dominance_ratio": 0.75},
            }
        )

        assert finding.origin is not None
        assert len(finding.signatures) == 2
        assert finding.origin.display_location == "Fl Wheel"

    def test_finding_defaults_none(self) -> None:
        finding = Finding(finding_id="F001")
        assert finding.evidence is None
        assert finding.location is None
        assert finding.confidence_assessment is None


class TestFindingEnrichments:
    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            pytest.param(0.75, 0.75, id="explicit-confidence"),
            pytest.param(None, 0.0, id="missing-confidence"),
        ],
    )
    def test_effective_confidence_cases(
        self,
        confidence: float | None,
        expected: float,
    ) -> None:
        finding = Finding(confidence=confidence)
        assert finding.effective_confidence == expected

    @pytest.mark.parametrize(
        ("finding", "expected"),
        [
            pytest.param(
                Finding(suspected_source="wheel/tire"),
                True,
                id="known-source",
            ),
            pytest.param(
                Finding(suspected_source="unknown"),
                False,
                id="placeholder-no-location",
            ),
            pytest.param(
                Finding(suspected_source="unknown", strongest_location="front_left_wheel"),
                True,
                id="placeholder-with-location",
            ),
            pytest.param(
                Finding(suspected_source="unknown_resonance"),
                False,
                id="unknown-resonance",
            ),
        ],
    )
    def test_is_actionable_cases(self, finding: Finding, expected: bool) -> None:
        assert finding.is_actionable is expected

    @pytest.mark.parametrize(
        ("finding", "expected"),
        [
            pytest.param(
                Finding(confidence=0.5, severity="diagnostic"),
                True,
                id="diagnostic",
            ),
            pytest.param(
                Finding(confidence=0.1, severity="diagnostic"),
                False,
                id="low-confidence",
            ),
            pytest.param(
                Finding(finding_id="REF_SPEED", confidence=0.9),
                False,
                id="reference",
            ),
            pytest.param(
                Finding(confidence=0.8, severity="info"),
                False,
                id="informational",
            ),
        ],
    )
    def test_should_surface_cases(self, finding: Finding, expected: bool) -> None:
        assert finding.should_surface is expected

    def test_rank_key_quantised(self) -> None:
        f1 = Finding(confidence=0.751, ranking_score=1.0)
        f2 = Finding(confidence=0.759, ranking_score=1.0)
        assert f1.rank_key == f2.rank_key

    def test_rank_key_different_scores(self) -> None:
        f1 = Finding(confidence=0.5, ranking_score=2.0)
        f2 = Finding(confidence=0.5, ranking_score=1.0)
        assert f1.rank_key > f2.rank_key

    @pytest.mark.parametrize(
        ("finding", "expected"),
        [
            pytest.param(
                Finding(confidence=0.8),
                pytest.approx(0.8 * 0.85),
                id="no-phase",
            ),
            pytest.param(
                Finding(confidence=0.8, cruise_fraction=1.0),
                pytest.approx(0.8),
                id="full-cruise",
            ),
        ],
    )
    def test_phase_adjusted_score_cases(self, finding: Finding, expected: float) -> None:
        assert finding.phase_adjusted_score == expected

    def test_is_stronger_than(self) -> None:
        f1 = Finding(confidence=0.8, ranking_score=1.0)
        f2 = Finding(confidence=0.5, ranking_score=1.0)
        assert f1.is_stronger_than(f2)
        assert not f2.is_stronger_than(f1)

    def test_with_id(self) -> None:
        finding = Finding(finding_id="F001", suspected_source="engine", confidence=0.7)
        renamed = finding.with_id("F002")
        assert renamed.finding_id == "F002"
        assert renamed.suspected_source == "engine"
        assert renamed.confidence == 0.7
        assert finding.finding_id == "F001"

    def test_from_payload_extracts_evidence_fields(self) -> None:
        finding = finding_from_payload(
            {
                "finding_id": "F001",
                "suspected_source": "bearing",
                "ranking_score": 1.5,
                "dominance_ratio": 0.85,
                "diffuse_excitation": True,
                "weak_spatial_separation": True,
                "phase_evidence": {"cruise_fraction": 0.6},
            }
        )

        assert finding.ranking_score == 1.5
        assert finding.dominance_ratio == 0.85
        assert finding.diffuse_excitation is True
        assert finding.weak_spatial_separation is True
        assert finding.cruise_fraction == pytest.approx(0.6)


def test_finding_payload_is_distinct_from_domain_finding() -> None:
    from vibesensor.domain import Finding as DomainFinding
    from vibesensor.shared.types.history_analysis_contracts import FindingPayload

    assert DomainFinding is not FindingPayload
