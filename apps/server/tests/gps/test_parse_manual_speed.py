"""Tests for _parse_manual_speed rejecting Inf/NaN/out-of-range values."""

from __future__ import annotations

import math

import pytest

from vibesensor.domain_models import _parse_manual_speed


@pytest.mark.parametrize(
    "value, expected",
    [
        (50, 50.0),
        (80.5, 80.5),
        (0.1, 0.1),
        (500, 500.0),
    ],
    ids=["int-50", "float-80.5", "small-positive", "upper-bound-500"],
)
def test_normal_values(value: float, expected: float) -> None:
    assert _parse_manual_speed(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        math.inf,
        -math.inf,
        math.nan,
        float("inf"),
        float("-inf"),
        float("nan"),
    ],
    ids=["inf", "neg-inf", "nan", "float-inf", "float-neg-inf", "float-nan"],
)
def test_non_finite_returns_none(value: float) -> None:
    assert _parse_manual_speed(value) is None


@pytest.mark.parametrize(
    "value",
    [-1, -50.0, -0.001],
    ids=["neg-int", "neg-float", "small-neg"],
)
def test_negative_returns_none(value: float) -> None:
    assert _parse_manual_speed(value) is None


def test_zero_returns_none() -> None:
    assert _parse_manual_speed(0) is None
    assert _parse_manual_speed(0.0) is None


def test_above_upper_bound_returns_none() -> None:
    assert _parse_manual_speed(500.1) is None
    assert _parse_manual_speed(1000) is None


@pytest.mark.parametrize(
    "value",
    [None, "", "fast", [], {}],
    ids=["none", "empty-str", "string", "list", "dict"],
)
def test_non_numeric_returns_none(value: object) -> None:
    assert _parse_manual_speed(value) is None
