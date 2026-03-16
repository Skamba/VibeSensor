"""Tests for DiagnosticReasoning domain object."""

from __future__ import annotations

import pytest

from vibesensor.domain import DiagnosticReasoning, Hypothesis, Signature, VibrationSource


class TestDiagnosticReasoningDefaults:
    def test_empty(self) -> None:
        dr = DiagnosticReasoning()
        assert dr.observations == ()
        assert dr.signatures == ()
        assert dr.hypotheses == ()

    def test_immutable(self) -> None:
        dr = DiagnosticReasoning()
        with pytest.raises(AttributeError):
            dr.observations = ()  # type: ignore[misc]


class TestHasUnresolvedHypotheses:
    def test_no_hypotheses(self) -> None:
        assert DiagnosticReasoning().has_unresolved_hypotheses is False

    def test_all_terminal(self) -> None:
        hyps = (
            Hypothesis(hypothesis_id="h1", source=VibrationSource.WHEEL_TIRE, status="supported"),
            Hypothesis(hypothesis_id="h2", source=VibrationSource.WHEEL_TIRE, status="retired"),
        )
        assert DiagnosticReasoning(hypotheses=hyps).has_unresolved_hypotheses is False

    def test_one_unresolved(self) -> None:
        hyps = (
            Hypothesis(hypothesis_id="h1", source=VibrationSource.WHEEL_TIRE, status="supported"),
            Hypothesis(hypothesis_id="h2", source=VibrationSource.WHEEL_TIRE, status="candidate"),
        )
        assert DiagnosticReasoning(hypotheses=hyps).has_unresolved_hypotheses is True


class TestPrimarySignature:
    def test_no_signatures(self) -> None:
        assert DiagnosticReasoning().primary_signature is None

    def test_returns_first(self) -> None:
        sigs = (
            Signature(key="s1", source=VibrationSource.WHEEL_TIRE, label="first"),
            Signature(key="s2", source=VibrationSource.WHEEL_TIRE, label="second"),
        )
        dr = DiagnosticReasoning(signatures=sigs)
        assert dr.primary_signature is not None
        assert dr.primary_signature.key == "s1"


class TestFromFindings:
    def test_happy_path(self) -> None:
        from vibesensor.domain.finding import Finding

        sig_a = Signature(key="s1", source=VibrationSource.WHEEL_TIRE, label="speed-dep")
        sig_b = Signature(key="s2", source=VibrationSource.ENGINE, label="rpm-dep")
        f1 = Finding(
            finding_id="F1",
            suspected_source=VibrationSource.WHEEL_TIRE,
            signatures=(sig_a,),
        )
        f2 = Finding(
            finding_id="F2",
            suspected_source=VibrationSource.ENGINE,
            signatures=(sig_a, sig_b),
        )
        dr = DiagnosticReasoning.from_findings([f1, f2])
        assert dr.observations == ()
        assert len(dr.hypotheses) == 2
        # Signatures are deduplicated
        assert len(dr.signatures) == 2
        assert dr.signatures[0].key == "s1"
        assert dr.signatures[1].key == "s2"

    def test_reference_exclusion(self) -> None:
        from vibesensor.domain.finding import Finding

        diag = Finding(
            finding_id="F1",
            suspected_source=VibrationSource.WHEEL_TIRE,
        )
        ref = Finding(
            finding_id="REF_ENGINE",
            suspected_source=VibrationSource.ENGINE,
        )
        dr = DiagnosticReasoning.from_findings([diag, ref])
        assert len(dr.hypotheses) == 1
        assert dr.hypotheses[0].source == VibrationSource.WHEEL_TIRE

    def test_empty_findings(self) -> None:
        dr = DiagnosticReasoning.from_findings([])
        assert dr.observations == ()
        assert dr.signatures == ()
        assert dr.hypotheses == ()

    def test_all_reference_findings(self) -> None:
        from vibesensor.domain.finding import Finding

        r1 = Finding(finding_id="REF_A", suspected_source=VibrationSource.WHEEL_TIRE)
        r2 = Finding(finding_id="REF_B", suspected_source=VibrationSource.ENGINE)
        dr = DiagnosticReasoning.from_findings([r1, r2])
        assert dr.signatures == ()
        assert dr.hypotheses == ()
        assert dr.observations == ()
