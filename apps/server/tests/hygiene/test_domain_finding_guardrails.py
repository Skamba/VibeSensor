"""Guardrails for Finding domain behavior and confidence ownership."""


def test_finalize_findings_returns_domain_findings() -> None:
    """``finalize_findings`` must return domain ``Finding`` objects."""
    from vibesensor.domain import Finding
    from vibesensor.use_cases.diagnostics.findings import finalize_findings

    domain_findings = finalize_findings(
        [
            Finding(finding_id="F_ORDER", confidence=0.7, suspected_source="wheel/tire"),
        ]
    )
    assert len(domain_findings) == 1
    assert isinstance(domain_findings[0], Finding)
    assert domain_findings[0].finding_id == "F001"


def test_select_top_causes_returns_domain_findings() -> None:
    """``select_top_causes`` must return domain ``Finding`` objects."""
    from test_support.findings import make_finding_payload

    from vibesensor.domain import Finding
    from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload
    from vibesensor.use_cases.diagnostics.top_cause_selection import select_top_causes

    findings = tuple(
        finding_from_payload(f)
        for f in [make_finding_payload(confidence=0.80, suspected_source="wheel/tire")]
    )
    domain_findings = select_top_causes(findings)
    assert len(domain_findings) == 1
    assert isinstance(domain_findings[0], Finding)


def test_finding_owns_confidence_label() -> None:
    """Finding must own confidence-tier classification (label, tone, pct)."""
    from vibesensor.domain import Finding

    high = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")
    label_key, tone, pct_text = high.confidence_label()
    assert label_key == "CONFIDENCE_HIGH"
    assert tone == "success"
    assert pct_text == "80%"

    medium = Finding(finding_id="F002", confidence=0.55, suspected_source="engine")
    label_key, tone, _ = medium.confidence_label()
    assert label_key == "CONFIDENCE_MEDIUM"
    assert tone == "warn"

    low = Finding(finding_id="F003", confidence=0.20, suspected_source="unknown")
    label_key, tone, _ = low.confidence_label()
    assert label_key == "CONFIDENCE_LOW"
    assert tone == "neutral"


def test_finding_confidence_negligible_strength_downgrade() -> None:
    """Finding with negligible strength should downgrade HIGH → MEDIUM."""
    from vibesensor.domain import Finding

    high = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")
    label_key, tone, _ = high.confidence_label(strength_band_key="negligible")
    assert label_key == "CONFIDENCE_MEDIUM"
    assert tone == "warn"


def test_classify_confidence_is_domain_owned() -> None:
    """Finding.classify_confidence is the canonical source of truth for confidence presentation."""
    from vibesensor.domain import Finding

    for conf in (0.80, 0.55, 0.20, 0.0):
        result = Finding.classify_confidence(conf)
        assert len(result) == 3
        assert all(isinstance(v, str) for v in result)


def test_confidence_assessment_tier_matches_domain_finding() -> None:
    """ConfidenceAssessment.tier must be consistent with Finding.classify_confidence."""
    from vibesensor.domain import ConfidenceAssessment, Finding

    for conf in [0.1, 0.3, 0.5, 0.7, 0.9]:
        label_key, _tone, _pct = Finding.classify_confidence(conf)
        ca = ConfidenceAssessment.assess(conf)
        assert ca.label_key == label_key, (
            f"ConfidenceAssessment.assess({conf}).label_key must match "
            f"Finding.classify_confidence({conf})[0]"
        )


def test_speed_profile_used_by_confidence_assessment() -> None:
    """ConfidenceAssessment must be the owner of confidence reasoning.

    ``certainty_label()`` was deleted; ``ConfidenceAssessment.assess()``
    is the single source of truth for confidence assessment. Report mapping
    uses ``ConfidenceAssessment.tier`` for layout gating.
    """
    from tests._paths import SERVER_ROOT

    report_presentation_path = SERVER_ROOT / "vibesensor" / "shared" / "report_presentation.py"
    source = report_presentation_path.read_text()
    assert "certainty_label" not in source, (
        "certainty_label was deleted; ConfidenceAssessment.assess() is the replacement"
    )
