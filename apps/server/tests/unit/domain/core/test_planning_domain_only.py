"""Prove that plan_test_actions operates on domain objects only."""

from __future__ import annotations

import inspect

from vibesensor.domain import Finding, TestPlan
from vibesensor.domain.services import plan_test_actions


def _make_finding(
    finding_id: str = "F001",
    source: str = "wheel/tire",
    confidence: float = 0.8,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        suspected_source=source,
        confidence=confidence,
    )


class TestPlanTestActionsDomainOnly:
    def test_returns_test_plan(self) -> None:
        findings = [_make_finding()]
        result = plan_test_actions(findings)
        assert isinstance(result, TestPlan)

    def test_empty_findings_gives_fallback(self) -> None:
        result = plan_test_actions([])
        assert result.has_actions

    def test_multiple_sources_deduplicated(self) -> None:
        findings = [
            _make_finding("F1", "wheel/tire"),
            _make_finding("F2", "wheel/tire"),
            _make_finding("F3", "engine"),
        ]
        result = plan_test_actions(findings)
        assert result.has_actions
        action_ids = [a.action_id for a in result.actions]
        assert len(action_ids) == len(set(action_ids)), "actions must be deduplicated"

    def test_least_invasive_ordering(self) -> None:
        findings = [
            _make_finding("F1", "engine"),
            _make_finding("F2", "wheel/tire"),
        ]
        result = plan_test_actions(findings)
        priorities = [a.priority for a in result.actions]
        assert priorities == sorted(priorities), "actions must be ordered least-invasive-first"

    def test_no_payload_types_in_signature(self) -> None:
        """plan_test_actions must not accept FindingPayload."""
        sig = inspect.signature(plan_test_actions)
        for param in sig.parameters.values():
            annotation = str(param.annotation)
            assert "FindingPayload" not in annotation
            assert "dict" not in annotation.lower() or "Mapping" not in annotation
