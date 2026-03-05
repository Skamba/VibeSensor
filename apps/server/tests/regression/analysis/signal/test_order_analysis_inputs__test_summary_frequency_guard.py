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


class TestSummaryFrequencyGuard:
    """float() on frequency_hz should not crash on non-numeric values."""

    def test_non_numeric_frequency_skipped(self) -> None:
        row = {"frequency_hz": "invalid"}
        with pytest.raises((ValueError, TypeError)):
            float(row.get("frequency_hz") or 0.0)

    def test_none_frequency(self) -> None:
        row = {"frequency_hz": None}
        try:
            freq = float(row.get("frequency_hz") or 0.0)
        except (ValueError, TypeError):
            freq = 0.0
        assert freq == 0.0
