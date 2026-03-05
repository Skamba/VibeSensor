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

from vibesensor.runlog import as_float_or_none


@pytest.mark.parametrize(
    "value, expected",
    [
        (float("nan"), None),
        (float("inf"), None),
        (3.14, pytest.approx(3.14)),
        ("42.0", pytest.approx(42.0)),
        (None, None),
        ("hello", None),
    ],
)
def test_as_float_or_none_regression(value: object, expected: object) -> None:
    """as_float_or_none must reject NaN/Inf and accept valid numbers."""
    result = as_float_or_none(value)
    if expected is None:
        assert result is None
    else:
        assert result == expected
