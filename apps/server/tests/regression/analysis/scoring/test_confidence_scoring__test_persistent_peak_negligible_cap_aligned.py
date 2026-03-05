"""Confidence and scoring regressions:
- Ranking score error denominator uses compliance (matches confidence formula)
- _suppress_engine_aliases filters before slicing (no lost valid findings)
- Single-sensor confidence no longer triple-penalised
- Persistent peak negligible cap aligned to 0.40 (matches order cap)
"""

from __future__ import annotations

import inspect

import vibesensor.analysis.findings as fmod


class TestPersistentPeakNegligibleCapAligned:
    """The negligible-strength cap for persistent peaks must be 0.40,
    matching the order-finding cap, so that a weak order finding at
    ~0.37 confidence always suppresses persistent peaks at the same
    frequency."""

    def test_persistent_peak_cap_value_in_source(self) -> None:
        src = inspect.getsource(fmod._build_persistent_peak_findings)
        # The negligible cap must be 0.40, not 0.35
        assert "min(confidence, 0.40)" in src, (
            "Persistent peak negligible cap must be 0.40 to align with order cap"
        )
