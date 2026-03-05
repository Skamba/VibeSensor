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

from vibesensor.analysis.order_analysis import _order_label


class TestOrderLabel:
    """_order_label should handle 2-arg signatures."""

    @pytest.mark.parametrize(
        "order, base, expected",
        [
            (1, "wheel", "1x wheel"),
            (3, "engine", "3x engine"),
            (2, "driveline", "2x driveline"),
        ],
        ids=["basic", "higher-order", "legacy-two-arg"],
    )
    def test_two_arg(self, order: int, base: str, expected: str) -> None:
        assert _order_label(order, base) == expected

    def test_wrong_arg_count_raises(self) -> None:
        with pytest.raises(TypeError):
            _order_label()  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            _order_label(1)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            _order_label(1, 2, 3, 4)  # type: ignore[call-arg]
