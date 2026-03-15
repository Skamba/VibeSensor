"""Tests for signature recognition service (T5.17)."""

from vibesensor.domain.diagnostics.finding import VibrationSource
from vibesensor.domain.diagnostics.observation import Observation
from vibesensor.domain.services.signature_recognition import recognize_signatures


def _obs(
    obs_id: str,
    signature_key: str,
    support_score: float = 0.5,
    source: VibrationSource = VibrationSource.WHEEL_TIRE,
) -> Observation:
    return Observation(
        observation_id=obs_id,
        kind="test",
        source=source,
        signature_key=signature_key,
        support_score=support_score,
    )


def test_multiple_observations_merge_into_one_signature():
    obs_a = _obs("obs-1", "flat_spot", support_score=0.3)
    obs_b = _obs("obs-2", "flat_spot", support_score=0.4)

    sigs = recognize_signatures([obs_a, obs_b])

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.key == "flat_spot"
    assert set(sig.observation_ids) == {"obs-1", "obs-2"}
    assert sig.support_score == min(1.0, 0.3 + 0.4)


def test_non_supporting_observations_excluded():
    good = _obs("obs-1", "flat_spot", support_score=0.5)
    zero_score = _obs("obs-2", "flat_spot", support_score=0.0)
    blank_key = _obs("obs-3", "", support_score=0.5)
    whitespace_key = _obs("obs-4", "   ", support_score=0.5)

    sigs = recognize_signatures([good, zero_score, blank_key, whitespace_key])

    assert len(sigs) == 1
    assert sigs[0].observation_ids == ("obs-1",)


def test_no_finding_id_dependency():
    obs_a = _obs("obs-1-1", "imbalance", support_score=0.6)
    obs_b = _obs("obs-2-1", "imbalance", support_score=0.3)

    sigs = recognize_signatures([obs_a, obs_b])

    assert len(sigs) == 1
    assert set(sigs[0].observation_ids) == {"obs-1-1", "obs-2-1"}


def test_signatures_sorted_by_score_desc():
    obs_low = _obs("obs-1", "minor_wobble", support_score=0.2)
    obs_high = _obs("obs-2", "severe_shake", support_score=0.9)

    sigs = recognize_signatures([obs_low, obs_high])

    assert len(sigs) == 2
    assert sigs[0].key == "severe_shake"
    assert sigs[1].key == "minor_wobble"


def test_observation_count_property():
    obs_a = _obs("obs-1", "flat_spot", support_score=0.3)
    obs_b = _obs("obs-2", "flat_spot", support_score=0.4)
    obs_c = _obs("obs-3", "flat_spot", support_score=0.2)

    sigs = recognize_signatures([obs_a, obs_b, obs_c])

    assert len(sigs) == 1
    assert sigs[0].observation_count == 3
