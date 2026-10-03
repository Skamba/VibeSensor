"""Pure report projection helper tests without PDF rendering dependencies."""

from __future__ import annotations

import pytest

from vibesensor.analysis.top_cause_selection import select_top_causes
from vibesensor.domain.finding import Finding
from vibesensor.summary.finding_fields import finding_from_payload


def _to_domain(*payloads: dict[str, object]) -> tuple[Finding, ...]:
    return tuple(finding_from_payload(p) for p in payloads)


def test_select_top_causes_groups_by_source() -> None:
    findings = _to_domain(
        {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.80,
            "frequency_hz_or_order": "1x wheel order",
        },
        {
            "finding_id": "F002",
            "suspected_source": "wheel/tire",
            "confidence": 0.65,
            "frequency_hz_or_order": "2x wheel order",
        },
        {
            "finding_id": "F003",
            "suspected_source": "engine",
            "confidence": 0.55,
            "frequency_hz_or_order": "2x engine order",
        },
    )
    causes = select_top_causes(findings)
    sources = [c.source_normalized for c in causes]
    assert sources.count("wheel/tire") == 1


def test_select_top_causes_empty_findings() -> None:
    causes = select_top_causes(())
    assert causes == ()


def test_select_top_causes_excludes_reference_findings() -> None:
    findings = _to_domain(
        {
            "finding_id": "REF_SPEED",
            "suspected_source": "unknown",
            "confidence": 1.0,
            "frequency_hz_or_order": "reference missing",
        },
        {
            "finding_id": "REF_WHEEL",
            "suspected_source": "wheel/tire",
            "confidence": 1.0,
            "frequency_hz_or_order": "reference missing",
        },
        {
            "finding_id": "REF_ENGINE",
            "suspected_source": "engine",
            "confidence": 1.0,
            "frequency_hz_or_order": "reference missing",
        },
    )
    causes = select_top_causes(findings)
    assert causes == ()


@pytest.mark.parametrize(
    ("confidence", "freq_hz"),
    [
        pytest.param(0.22, "92.0 Hz", id="low_confidence"),
        pytest.param(0.99, "120.0 Hz", id="high_confidence"),
    ],
)
def test_select_top_causes_excludes_informational_transient_findings(
    confidence: float,
    freq_hz: str,
) -> None:
    findings = _to_domain(
        {
            "finding_id": "F007",
            "severity": "info",
            "suspected_source": "transient_impact",
            "peak_classification": "transient",
            "confidence": confidence,
            "frequency_hz_or_order": freq_hz,
        },
    )
    causes = select_top_causes(findings)
    assert causes == ()


def test_select_top_causes_prefers_diagnostic_over_info() -> None:
    findings = _to_domain(
        {
            "finding_id": "F009",
            "severity": "info",
            "suspected_source": "transient_impact",
            "peak_classification": "transient",
            "confidence": 0.99,
            "frequency_hz_or_order": "120.0 Hz",
        },
        {
            "finding_id": "F010",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
            "confidence": 0.26,
            "frequency_hz_or_order": "1x wheel order",
        },
    )
    causes = select_top_causes(findings)
    assert len(causes) == 1
    assert causes[0].source_normalized == "wheel/tire"


def test_select_top_causes_prefers_cruise_phase_evidence() -> None:
    """Cruise-phase evidence should break ties at equal raw confidence."""
    findings = _to_domain(
        {
            "finding_id": "F_A",
            "severity": "diagnostic",
            "suspected_source": "driveline",
            "confidence": 0.60,
            "frequency_hz_or_order": "3x driveshaft",
        },
        {
            "finding_id": "F_B",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
            "confidence": 0.60,
            "frequency_hz_or_order": "1x wheel order",
            "phase_evidence": {"cruise_fraction": 1.0, "phases_detected": ["cruise"]},
        },
    )
    causes = select_top_causes(findings)
    assert len(causes) == 2
    assert causes[0].source_normalized == "wheel/tire"
    assert causes[1].source_normalized == "driveline"


def test_select_top_causes_phase_evidence_in_output() -> None:
    phase_ev = {"cruise_fraction": 0.85, "phases_detected": ["cruise", "acceleration"]}
    findings = _to_domain(
        {
            "finding_id": "F_C",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
            "confidence": 0.75,
            "frequency_hz_or_order": "1x wheel order",
            "phase_evidence": phase_ev,
        },
    )
    causes = select_top_causes(findings)
    assert len(causes) == 1
    assert causes[0].cruise_fraction == pytest.approx(0.85)


def test_select_top_causes_no_phase_evidence_still_works() -> None:
    findings = _to_domain(
        {
            "finding_id": "F_D",
            "severity": "diagnostic",
            "suspected_source": "engine",
            "confidence": 0.55,
            "frequency_hz_or_order": "2x engine order",
        },
    )
    causes = select_top_causes(findings)
    assert len(causes) == 1
    assert causes[0].source_normalized == "engine"
