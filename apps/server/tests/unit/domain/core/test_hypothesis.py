"""Tests for Hypothesis.from_finding classmethod."""

from vibesensor.domain.diagnostics.confidence_assessment import ConfidenceAssessment
from vibesensor.domain.diagnostics.finding import Finding, VibrationSource
from vibesensor.domain.diagnostics.hypothesis import Hypothesis, HypothesisStatus
from vibesensor.domain.diagnostics.signature import Signature


def _make_signature(key: str = "sig-test") -> Signature:
    return Signature(
        key=key,
        source=VibrationSource.WHEEL_TIRE,
        label="Test signature",
        support_score=0.5,
        observation_ids=("obs-1",),
    )


class TestFromFindingHighConfidence:
    def test_status_is_supported(self) -> None:
        finding = Finding(
            finding_id="F001",
            suspected_source=VibrationSource.WHEEL_TIRE,
            confidence=0.75,
            confidence_assessment=ConfidenceAssessment(
                raw_confidence=0.75,
                label_key="CONFIDENCE_HIGH",
                tone="success",
                pct_text="75%",
                reason="Strong harmonic match",
            ),
        )
        sigs = (_make_signature("wheel-1h"),)
        hyp = Hypothesis.from_finding(finding, sigs)

        assert hyp.status is HypothesisStatus.SUPPORTED
        assert hyp.hypothesis_id == "F001"
        assert hyp.source is VibrationSource.WHEEL_TIRE
        assert hyp.signature_keys == ("wheel-1h",)
        assert hyp.support_score == 0.75
        assert hyp.contradiction_score == 0.0
        assert hyp.rationale == ("Strong harmonic match",)


class TestFromFindingLowConfidence:
    def test_status_is_inconclusive(self) -> None:
        finding = Finding(
            finding_id="F002",
            suspected_source=VibrationSource.ENGINE,
            confidence=0.20,
            confidence_assessment=ConfidenceAssessment(
                raw_confidence=0.20,
                label_key="CONFIDENCE_LOW",
                tone="neutral",
                pct_text="20%",
                reason="Weak signal",
            ),
        )
        sigs = (_make_signature("eng-1"),)
        hyp = Hypothesis.from_finding(finding, sigs)

        assert hyp.status is HypothesisStatus.INCONCLUSIVE
        assert hyp.support_score == 0.20
        assert hyp.rationale == ("Weak signal",)


class TestFromFindingNoConfidenceAssessment:
    def test_rationale_is_empty(self) -> None:
        finding = Finding(
            finding_id="F003",
            suspected_source=VibrationSource.DRIVELINE,
            confidence=0.50,
        )
        sigs = (_make_signature("dl-1"), _make_signature("dl-2"))
        hyp = Hypothesis.from_finding(finding, sigs)

        assert hyp.rationale == ()
        assert hyp.signature_keys == ("dl-1", "dl-2")
        assert hyp.status is HypothesisStatus.SUPPORTED


class TestFromFindingNoFindingId:
    def test_fallback_id(self) -> None:
        finding = Finding(
            suspected_source=VibrationSource.ENGINE,
            confidence=0.10,
        )
        sigs = ()
        hyp = Hypothesis.from_finding(finding, sigs)

        assert hyp.hypothesis_id == "hyp-engine"
        assert hyp.signature_keys == ()
        assert hyp.status is HypothesisStatus.INCONCLUSIVE
