"""Confidence and scoring regressions:
- Ranking score error denominator uses compliance (matches confidence formula)
- _suppress_engine_aliases filters before slicing (no lost valid findings)
- Single-sensor confidence no longer triple-penalised
- Persistent peak negligible cap aligned to 0.40 (matches order cap)
"""

from __future__ import annotations

from vibesensor.analysis.findings import (
    _suppress_engine_aliases,
)


class TestSuppressEngineAliasesFilterBeforeSlice:
    """Suppressed engine findings must not consume top-5 slots, preventing
    valid findings at position 6+ from being returned."""

    def test_valid_finding_not_lost_after_suppression(self) -> None:
        # Build 7 findings: 2 wheel, 3 engine (will be suppressed below
        # ORDER_MIN_CONFIDENCE), 2 driveshaft at end.
        findings: list[tuple[float, dict]] = [
            (
                1.0,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.80,
                    "_ranking_score": 1.0,
                },
            ),
            (
                0.9,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.70,
                    "_ranking_score": 0.9,
                },
            ),
            # These 3 engine findings will be suppressed below threshold
            (
                0.7,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.40,
                    "_ranking_score": 0.7,
                },
            ),
            (
                0.6,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.38,
                    "_ranking_score": 0.6,
                },
            ),
            (
                0.5,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.35,
                    "_ranking_score": 0.5,
                },
            ),
            # These valid findings must NOT be lost
            (
                0.4,
                {
                    "suspected_source": "driveline",
                    "confidence_0_to_1": 0.55,
                    "_ranking_score": 0.4,
                },
            ),
            (
                0.3,
                {
                    "suspected_source": "driveline",
                    "confidence_0_to_1": 0.50,
                    "_ranking_score": 0.3,
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        driveline = [f for f in result if f["suspected_source"] == "driveline"]
        assert len(driveline) >= 1, (
            "Driveline findings must not be lost when suppressed engine aliases are filtered out"
        )

    def test_suppressed_engine_below_threshold_excluded(self) -> None:
        findings: list[tuple[float, dict]] = [
            (
                1.0,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.80,
                    "_ranking_score": 1.0,
                },
            ),
            (
                0.5,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.30,
                    "_ranking_score": 0.5,
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        engine = [f for f in result if f["suspected_source"] == "engine"]
        # After suppression: 0.30 * 0.60 = 0.18 < ORDER_MIN_CONFIDENCE (0.25)
        assert len(engine) == 0, "Suppressed engine finding below threshold must be excluded"
