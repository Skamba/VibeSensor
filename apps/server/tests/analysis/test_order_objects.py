"""Tests for OrderMatchAccumulator properties and OrderAnalysisSession."""

from __future__ import annotations

import pytest

from vibesensor.analysis.order_analysis import (
    OrderAnalysisSession,
    OrderMatchAccumulator,
)


# ===========================================================================
# OrderMatchAccumulator computed properties
# ===========================================================================


def _make_accumulator(
    possible: int = 20,
    matched: int = 10,
    matched_points: list | None = None,
) -> OrderMatchAccumulator:
    """Build an accumulator with sensible defaults for testing."""
    if matched_points is None:
        matched_points = [
            {"location": "front_left", "speed_kmh": 60.0, "amp": 0.05}
            for _ in range(matched)
        ]
    return OrderMatchAccumulator(
        possible=possible,
        matched=matched,
        matched_amp=[0.05] * matched,
        matched_floor=[0.005] * matched,
        rel_errors=[0.01] * matched,
        predicted_vals=[50.0] * matched,
        measured_vals=[50.5] * matched,
        matched_points=matched_points,
        ref_sources={"speed+tire"},
        possible_by_speed_bin={"60-80": possible},
        matched_by_speed_bin={"60-80": matched},
        possible_by_phase={},
        matched_by_phase={},
        possible_by_location={"front_left": possible},
        matched_by_location={"front_left": matched},
        has_phases=False,
        compliance=1.0,
    )


class TestOrderMatchAccumulatorProperties:
    def test_match_rate(self) -> None:
        m = _make_accumulator(possible=20, matched=10)
        assert m.match_rate == pytest.approx(0.50)

    def test_match_rate_zero_possible(self) -> None:
        m = _make_accumulator(possible=0, matched=0, matched_points=[])
        assert m.match_rate == pytest.approx(0.0)

    def test_unique_match_locations(self) -> None:
        points = [
            {"location": "front_left", "speed_kmh": 60.0, "amp": 0.05},
            {"location": "front_right", "speed_kmh": 60.0, "amp": 0.05},
            {"location": "front_left", "speed_kmh": 70.0, "amp": 0.04},
        ]
        m = _make_accumulator(matched=3, matched_points=points)
        assert m.unique_match_locations == {"front_left", "front_right"}

    def test_unique_match_locations_empty(self) -> None:
        m = _make_accumulator(matched=0, matched_points=[])
        assert m.unique_match_locations == set()

    def test_is_eligible_true(self) -> None:
        m = _make_accumulator(possible=20, matched=10)
        assert m.is_eligible() is True

    def test_is_eligible_false_low_possible(self) -> None:
        m = _make_accumulator(possible=2, matched=2, matched_points=[{"location": "x"}] * 2)
        assert m.is_eligible() is False

    def test_is_eligible_false_low_matched(self) -> None:
        m = _make_accumulator(possible=20, matched=1, matched_points=[{"location": "x"}])
        assert m.is_eligible() is False


# ===========================================================================
# OrderAnalysisSession
# ===========================================================================


class TestOrderAnalysisSession:
    def test_empty_samples(self) -> None:
        session = OrderAnalysisSession(
            metadata={},
            samples=[],
            speed_sufficient=True,
            steady_speed=False,
            speed_stddev_kmh=5.0,
            tire_circumference_m=2.0,
            engine_ref_sufficient=False,
            raw_sample_rate_hz=100.0,
            connected_locations=set(),
            lang="en",
        )
        assert session.analyze() == []

    def test_no_sample_rate_returns_empty(self) -> None:
        session = OrderAnalysisSession(
            metadata={},
            samples=[{"speed_kmh": 60.0}],
            speed_sufficient=True,
            steady_speed=False,
            speed_stddev_kmh=5.0,
            tire_circumference_m=2.0,
            engine_ref_sufficient=False,
            raw_sample_rate_hz=None,
            connected_locations=set(),
            lang="en",
        )
        assert session.analyze() == []

    def test_returns_list_of_findings(self) -> None:
        """Smoke test with minimal matching data."""
        session = OrderAnalysisSession(
            metadata={},
            samples=[],
            speed_sufficient=False,
            steady_speed=False,
            speed_stddev_kmh=None,
            tire_circumference_m=None,
            engine_ref_sufficient=False,
            raw_sample_rate_hz=100.0,
            connected_locations=set(),
            lang="en",
        )
        results = session.analyze()
        assert isinstance(results, list)
