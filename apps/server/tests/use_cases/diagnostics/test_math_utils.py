from __future__ import annotations

import pytest

from vibesensor.use_cases.diagnostics.math_utils import (
    _max_or_none,
    _mean_or_none,
    _min_or_none,
    _ratio_or_zero,
    _stddev_or_none,
)


def test_summary_numeric_helpers_return_none_for_empty_iterables() -> None:
    assert _mean_or_none(()) is None
    assert _max_or_none(()) is None
    assert _min_or_none(()) is None
    assert _stddev_or_none(()) is None


def test_summary_numeric_helpers_preserve_expected_values() -> None:
    values = (1.0, 2.0, 5.0)

    assert _mean_or_none(values) == pytest.approx(8.0 / 3.0)
    assert _max_or_none(values) == 5.0
    assert _min_or_none(values) == 1.0
    assert _stddev_or_none(values) == pytest.approx(1.699673171197595)


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (3, 0, 0.0),
        (3, -2, 0.0),
        (3, 2, 1.5),
        (2.5, 4, 0.625),
    ],
)
def test_ratio_or_zero_handles_zero_and_positive_denominators(
    numerator: int | float,
    denominator: int | float,
    expected: float,
) -> None:
    assert _ratio_or_zero(numerator, denominator) == pytest.approx(expected)
