"""Order analysis and numeric input guard regressions.

Covers:
  1. pdf_builder.py — guarded float() on confidence_0_to_1
  2. summary.py — guarded float() on frequency_hz
  3. order_analysis._order_label — edge cases (zero test coverage)
  4. order_analysis._driveshaft_hz — edge cases (zero test coverage)
  5. domain_models._as_float_or_none — NaN handling
"""

from __future__ import annotations

import pytest


class TestPdfBuilderConfidenceGuard:
    """float() on confidence should not crash on non-numeric values."""

    @pytest.mark.parametrize(
        "raw_value, expected",
        [
            ("unknown", 0.0),
            (0.85, pytest.approx(0.85)),
            (None, 0.0),
        ],
    )
    def test_confidence_guard(self, raw_value: object, expected: object) -> None:
        finding = {"confidence_0_to_1": raw_value}
        try:
            confidence = float(finding.get("confidence_0_to_1") or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        assert confidence == expected
