"""Guardrails for Finding domain behavior and confidence ownership."""

from __future__ import annotations

import pytest

from vibesensor.analysis.findings import finalize_findings
from vibesensor.analysis.top_cause_selection import select_top_causes
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import ConfidenceLevel


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
    ("confidence", "expected"),
    [
        pytest.param(0.80, ConfidenceLevel.STRONG, id="strong"),
        pytest.param(0.55, ConfidenceLevel.MODERATE, id="moderate"),
        pytest.param(0.20, ConfidenceLevel.WEAK, id="weak"),
        pytest.param(float("nan"), ConfidenceLevel.WEAK, id="nan"),
    ],
)
def test_classify_confidence_is_domain_owned(
    confidence: float,
    expected: ConfidenceLevel,
) -> None:
    """Finding.classify_confidence is the canonical source of the user-facing confidence level."""
    assert Finding.classify_confidence(confidence) == expected
