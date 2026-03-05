"""Confidence and scoring regressions:
- Ranking score error denominator uses compliance (matches confidence formula)
- _suppress_engine_aliases filters before slicing (no lost valid findings)
- Single-sensor confidence no longer triple-penalised
- Persistent peak negligible cap aligned to 0.40 (matches order cap)
"""

from __future__ import annotations

import inspect

from vibesensor.analysis.findings import (
    _build_order_findings,
)


class TestRankingScoreErrorDenominator:
    """The ranking_score error term must use the same compliance-adjusted
    denominator as the confidence formula (0.25 * compliance)."""

    def test_no_hardcoded_denominator_in_ranking(self) -> None:
        """Source must not hardcode 0.5 denominator for ranking error."""
        src = inspect.getsource(_build_order_findings)
        # Old code had a hardcoded 0.5 denominator; new code derives from compliance.
        assert "mean_rel_err / 0.5" not in src, (
            "ranking_score must not hardcode error denominator to 0.5"
        )
        assert "ranking_error_denom" in src, (
            "ranking_score must use a compliance-derived error denominator"
        )
