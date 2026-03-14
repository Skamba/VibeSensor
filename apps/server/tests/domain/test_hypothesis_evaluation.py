"""Tests for hypothesis evaluation service."""

from vibesensor.domain.finding import VibrationSource
from vibesensor.domain.hypothesis import Hypothesis, HypothesisStatus
from vibesensor.domain.services.hypothesis_evaluation import evaluate_hypotheses
from vibesensor.domain.signature import Signature


def _make_signature(key: str = "sig-test", score: float = 0.5) -> Signature:
    return Signature(
        key=key,
        source=VibrationSource.WHEEL_TIRE,
        label="Test signature",
        support_score=score,
        observation_ids=("obs-1",),
    )


def test_supported_above_threshold() -> None:
    sig = _make_signature(score=0.5)
    (hyp,) = evaluate_hypotheses([sig])
    assert hyp.status is HypothesisStatus.SUPPORTED
    assert hyp.is_supported


def test_inconclusive_below_threshold() -> None:
    sig = _make_signature(score=0.3)
    (hyp,) = evaluate_hypotheses([sig])
    assert hyp.status is HypothesisStatus.INCONCLUSIVE
    assert not hyp.is_supported


def test_threshold_defined_on_hypothesis() -> None:
    assert Hypothesis.SUPPORTED_THRESHOLD == 0.40


def test_hypothesis_id_from_signature_key() -> None:
    sig = _make_signature(key="wheel-imbalance-dominant")
    (hyp,) = evaluate_hypotheses([sig])
    assert hyp.hypothesis_id == "hyp-wheel-imbalance-dominant"
