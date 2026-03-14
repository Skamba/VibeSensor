from __future__ import annotations

from vibesensor.domain import Finding, Hypothesis, HypothesisStatus, VibrationSource
from vibesensor.domain.services import plan_test_actions


def test_plan_test_actions_accepts_domain_findings_and_hypotheses() -> None:
    findings = [
        Finding(
            suspected_source="engine",
            strongest_location="engine bay",
            strongest_speed_band="50-60 km/h",
            frequency_hz=32.0,
            confidence=0.74,
        )
    ]
    hypotheses = [
        Hypothesis(
            hypothesis_id="hyp-engine-1x",
            source=VibrationSource.ENGINE,
            status=HypothesisStatus.SUPPORTED,
            support_score=0.74,
        )
    ]

    plan = plan_test_actions(findings, hypotheses, lang="en")

    assert len(plan.prioritized_actions) > 0
    assert plan.prioritized_actions[0].action_id == "engine_mounts_and_accessories"
    assert plan.requires_additional_data is False