"""Guardrails for Finding domain behavior and confidence ownership."""

from __future__ import annotations

import pytest

from vibesensor.domain import ConfidenceAssessment, Finding, RunCapture, TestRun
from vibesensor.use_cases.diagnostics.findings import finalize_findings
from vibesensor.use_cases.diagnostics.top_cause_selection import select_top_causes


def test_finalize_findings_returns_domain_findings() -> None:
    """``finalize_findings`` must return domain ``Finding`` objects."""
    domain_findings = finalize_findings(
        [
            Finding(finding_id="F_LOW", confidence=0.2, suspected_source="engine"),
            Finding(finding_id="F_ORDER", confidence=0.7, suspected_source="wheel/tire"),
        ]
    )
    assert all(isinstance(finding, Finding) for finding in domain_findings)
    assert [finding.finding_id for finding in domain_findings] == ["F001", "F002"]
    assert [finding.suspected_source for finding in domain_findings] == [
        "wheel/tire",
        "engine",
    ]


def test_select_top_causes_returns_domain_findings() -> None:
    """``select_top_causes`` must return domain ``Finding`` objects."""
    strong = Finding(
        finding_id="F001",
        confidence=0.80,
        suspected_source="wheel/tire",
        vibration_strength_db=12.0,
    )
    weak = Finding(
        finding_id="F002",
        confidence=0.30,
        suspected_source="engine",
        vibration_strength_db=4.0,
    )
    findings = (weak, strong)
    domain_findings = select_top_causes(findings, drop_off_points=100.0)
    assert domain_findings == (strong, weak)
    assert all(isinstance(finding, Finding) for finding in domain_findings)


@pytest.mark.parametrize(
    ("confidence", "expected_label", "expected_tone", "expected_pct"),
    [
        pytest.param(0.80, "CONFIDENCE_HIGH", "success", "80%", id="high"),
        pytest.param(0.55, "CONFIDENCE_MEDIUM", "warn", "55%", id="medium"),
        pytest.param(0.20, "CONFIDENCE_LOW", "neutral", "20%", id="low"),
    ],
)
def test_finding_owns_confidence_label(
    confidence: float,
    expected_label: str,
    expected_tone: str,
    expected_pct: str,
) -> None:
    """Finding must own confidence-tier classification (label, tone, pct)."""
    finding = Finding(finding_id="F001", confidence=confidence, suspected_source="wheel/tire")

    assert finding.confidence_label() == (expected_label, expected_tone, expected_pct)


def test_finding_confidence_negligible_strength_downgrade() -> None:
    """Finding with negligible strength should downgrade HIGH → MEDIUM."""
    high = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")
    label_key, tone, _ = high.confidence_label(strength_band_key="negligible")
    assert label_key == "CONFIDENCE_MEDIUM"
    assert tone == "warn"
    assert ConfidenceAssessment.assess(0.80, strength_band_key="negligible").downgraded is True


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        pytest.param(0.80, ("CONFIDENCE_HIGH", "success", "80%"), id="high"),
        pytest.param(0.55, ("CONFIDENCE_MEDIUM", "warn", "55%"), id="medium"),
        pytest.param(0.20, ("CONFIDENCE_LOW", "neutral", "20%"), id="low"),
        pytest.param(float("nan"), ("CONFIDENCE_LOW", "neutral", "0%"), id="nan"),
    ],
)
def test_classify_confidence_is_domain_owned(
    confidence: float,
    expected: tuple[str, str, str],
) -> None:
    """Finding.classify_confidence is the canonical source of truth for confidence presentation."""
    assert Finding.classify_confidence(confidence) == expected


def test_confidence_assessment_tier_matches_domain_finding() -> None:
    """ConfidenceAssessment.tier must be consistent with Finding.classify_confidence."""
    for conf in [0.1, 0.3, 0.5, 0.7, 0.9]:
        label_key, _tone, _pct = Finding.classify_confidence(conf)
        ca = ConfidenceAssessment.assess(conf)
        assert ca.label_key == label_key, (
            f"ConfidenceAssessment.assess({conf}).label_key must match "
            f"Finding.classify_confidence({conf})[0]"
        )
        assert ca.pct_text == f"{round(conf * 100):.0f}%"
        assert ca.tier in {"A", "B", "C"}


def test_speed_profile_used_by_confidence_assessment() -> None:
    """ConfidenceAssessment must be the owner of confidence reasoning.

    ``certainty_label()`` was deleted; ``ConfidenceAssessment.assess()``
    is the single source of truth for confidence assessment. Report mapping
    uses ``ConfidenceAssessment.tier`` for layout gating.
    """
    finding = Finding(finding_id="F001", confidence=0.85, suspected_source="wheel/tire")
    run_with_gap = TestRun(
        capture=RunCapture(run_id="guard"),
        findings=(Finding(finding_id="REF_SPEED"), finding),
        top_causes=(finding,),
    )
    assessment = ConfidenceAssessment.assess(
        finding.confidence or 0.0,
        steady_speed=False,
        has_reference_gaps=run_with_gap.has_relevant_reference_gap(finding.suspected_source),
        weak_spatial=True,
        sensor_count=1,
    )

    assert assessment.label_key == "CONFIDENCE_HIGH"
    assert assessment.tier == "B"
    assert assessment.is_conclusive is False
    assert "Missing reference data" in assessment.reason
    assert "Speed was not steady" in assessment.reason
    assert "Single sensor" in assessment.reason
