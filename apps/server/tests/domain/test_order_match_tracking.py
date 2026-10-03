from __future__ import annotations

import pytest

from vibesensor.domain.order_match import (
    OrderMatchObservation,
    frequency_tracking_slope,
    trend_moves,
)


def _points(pairs: list[tuple[float, float]]) -> list[OrderMatchObservation]:
    return [
        OrderMatchObservation(
            predicted_hz=predicted,
            matched_hz=matched,
            rel_error=abs(matched - predicted) / predicted,
            amp=0.01,
            location="front-left",
        )
        for predicted, matched in pairs
    ]


def test_order_that_follows_its_prediction_has_slope_one() -> None:
    sweep = [(10.0 + 0.2 * i, 10.0 + 0.2 * i + (0.05 if i % 2 else -0.05)) for i in range(20)]
    assert frequency_tracking_slope(_points(sweep)) == pytest.approx(1.0, abs=0.1)


def test_fixed_tone_crossed_by_the_prediction_has_slope_zero() -> None:
    crossing = [(12.0 + 0.1 * i, 12.9) for i in range(20)]
    # A couple of stray matches elsewhere do not move the robust slope.
    stray = [(10.0, 10.2), (14.5, 14.4)]
    assert frequency_tracking_slope(_points(crossing + stray)) == pytest.approx(0.0, abs=0.05)


def test_too_few_matches_have_no_slope() -> None:
    assert frequency_tracking_slope(_points([(12.0, 12.0), (13.0, 12.9), (14.0, 14.1)])) is None


@pytest.mark.parametrize(
    ("speeds", "moves"),
    [
        pytest.param([60.0 + 2.0 * i for i in range(20)], True, id="sweep"),
        pytest.param([80.0] * 20, False, id="steady"),
        # GPS jitter of +/-8 km/h around a steady 80 km/h averages out per 2 s.
        pytest.param([88.0 if i % 2 else 72.0 for i in range(20)], False, id="noisy-steady"),
    ],
)
def test_speed_trend_moves_only_when_the_speed_really_changes(
    speeds: list[float], moves: bool
) -> None:
    assert trend_moves((0.5 * i, speed) for i, speed in enumerate(speeds)) is moves
