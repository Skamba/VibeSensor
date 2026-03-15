"""Tests for the Diagnosis domain object."""

from __future__ import annotations

import pytest

from vibesensor.domain import (
    Diagnosis,
    DiagnosticCase,
    DiagnosticCaseEpistemicRule,
    Finding,
)


def _finding(
    finding_id: str,
    *,
    source: str = "wheel/tire",
    confidence: float = 0.8,
    location: str | None = "front_left",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        suspected_source=source,
        confidence=confidence,
        strongest_location=location,
    )


class TestDiagnosisConstruction:
    def test_frozen(self) -> None:
        f = _finding("F001")
        d = Diagnosis.from_finding_group(
            ("wheel/tire", "front_left"),
            (f,),
            DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
        )
        with pytest.raises(AttributeError):
            d.diagnosis_id = "other"  # type: ignore[misc]

    def test_all_fields_populated(self) -> None:
        f1 = _finding("F001")
        f2 = _finding("F002", confidence=0.9)
        d = Diagnosis.from_finding_group(
            ("wheel/tire", "front_left"),
            (f1, f2),
            DiagnosticCaseEpistemicRule.STRENGTHENING,
        )
        assert d.diagnosis_id == "wheel/tire:front_left"
        assert d.source_key == ("wheel/tire", "front_left")
        assert d.representative_finding is f2
        assert d.epistemic_rule is DiagnosticCaseEpistemicRule.STRENGTHENING
        assert d.source_findings == (f1, f2)


class TestFromFindingGroup:
    def test_representative_is_last(self) -> None:
        f1 = _finding("F001", confidence=0.9)
        f2 = _finding("F002", confidence=0.4)
        d = Diagnosis.from_finding_group(
            ("wheel/tire", "front_left"),
            (f1, f2),
            DiagnosticCaseEpistemicRule.WEAKENING,
        )
        assert d.representative_finding is f2

    def test_single_finding(self) -> None:
        f = _finding("F001")
        d = Diagnosis.from_finding_group(
            ("wheel/tire", "front_left"),
            (f,),
            DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
        )
        assert d.representative_finding is f
        assert d.source_findings == (f,)

    def test_empty_findings_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one finding"):
            Diagnosis.from_finding_group(
                ("wheel/tire", "front_left"),
                (),
                DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
            )

    def test_diagnosis_id_format_with_location(self) -> None:
        f = _finding("F001")
        d = Diagnosis.from_finding_group(
            ("wheel/tire", "front_left"),
            (f,),
            DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
        )
        assert d.diagnosis_id == "wheel/tire:front_left"

    def test_diagnosis_id_format_unlocalized(self) -> None:
        f = _finding("F001", location=None)
        d = Diagnosis.from_finding_group(
            ("engine", None),
            (f,),
            DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
        )
        assert d.diagnosis_id == "engine:unlocalized"


class TestIsActionable:
    def test_delegates_to_representative_actionable(self) -> None:
        f = _finding("F001", source="wheel/tire", confidence=0.8)
        d = Diagnosis.from_finding_group(
            ("wheel/tire", "front_left"),
            (f,),
            DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
        )
        assert d.is_actionable is True

    def test_delegates_to_representative_not_actionable(self) -> None:
        f = _finding("F001", source="unknown", location="unknown")
        d = Diagnosis.from_finding_group(
            ("unknown", None),
            (f,),
            DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
        )
        assert d.is_actionable is False

    def test_latest_wins_not_aggregate_strength(self) -> None:
        """Strong old run + weak latest run → is_actionable uses representative (latest)."""
        strong_old = _finding("F001", source="wheel/tire", confidence=0.95)
        weak_latest = _finding("F002", source="unknown", location="unknown")
        d = Diagnosis.from_finding_group(
            ("wheel/tire", "front_left"),
            (strong_old, weak_latest),
            DiagnosticCaseEpistemicRule.WEAKENING,
        )
        # Representative is weak_latest which is not actionable
        assert d.is_actionable is weak_latest.is_actionable


class TestDiagnosticCaseWithDiagnoses:
    def test_reconcile_produces_diagnosis_objects(self) -> None:
        """reconcile() must produce Diagnosis objects, not bare Findings."""
        from vibesensor.domain import ConfigurationSnapshot, Run, TestRun

        f = _finding("F001", source="wheel/tire", confidence=0.8)
        case = DiagnosticCase.start()
        case = case.add_run(
            TestRun(
                run=Run(run_id="run-1"),
                configuration_snapshot=ConfigurationSnapshot(),
                findings=(f,),
                top_causes=(f,),
            ),
        )
        assert len(case.diagnoses) == 1
        assert isinstance(case.diagnoses[0], Diagnosis)
        assert case.diagnoses[0].representative_finding is f

    def test_reconcile_epistemic_rule_assigned(self) -> None:
        """reconcile() assigns an epistemic rule to each diagnosis."""
        from vibesensor.domain import ConfigurationSnapshot, Run, TestRun

        f1 = _finding("F001", source="wheel/tire", confidence=0.5)
        f2 = _finding("F002", source="wheel/tire", confidence=0.9)
        case = DiagnosticCase.start()
        case = case.add_run(
            TestRun(
                run=Run(run_id="run-1"),
                configuration_snapshot=ConfigurationSnapshot(),
                findings=(f1,),
                top_causes=(f1,),
            ),
        )
        case = case.add_run(
            TestRun(
                run=Run(run_id="run-2"),
                configuration_snapshot=ConfigurationSnapshot(),
                findings=(f2,),
                top_causes=(f2,),
            ),
        )
        assert len(case.diagnoses) == 1
        assert case.diagnoses[0].epistemic_rule is DiagnosticCaseEpistemicRule.STRENGTHENING
        assert len(case.diagnoses[0].source_findings) == 2
