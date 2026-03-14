"""Domain planning service for next-step diagnostic actions."""

from __future__ import annotations

from collections.abc import Sequence

from ..finding import Finding
from ..hypothesis import Hypothesis
from ..test_plan import TestPlan


def plan_test_actions(
    findings: Sequence[Finding],
    hypotheses: Sequence[Hypothesis],
    *,
    lang: str,
) -> TestPlan:
    """Build a domain test plan from domain findings and hypotheses.

    The current planning rules are still owned by the analysis adapter layer.
    This service establishes the domain-facing entrypoint so pipeline callers
    no longer need to pass payload findings into planning.
    """
    from ...analysis.test_plan import build_domain_test_plan_from_findings

    return build_domain_test_plan_from_findings(findings, lang)