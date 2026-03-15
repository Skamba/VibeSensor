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
