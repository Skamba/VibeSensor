"""Tests for OrderMatchAccumulator properties and OrderAnalysisSession."""

from __future__ import annotations

import pytest

import vibesensor.use_cases.diagnostics.order_analysis as order_analysis_module
from vibesensor.domain import OrderMatchObservation, VibrationSource
from vibesensor.use_cases.diagnostics.order_analysis import (
    OrderFindingBuildContext,
    OrderMatchAccumulator,
)
from vibesensor.use_cases.diagnostics.order_pipeline import OrderAnalysisSession
from vibesensor.use_cases.diagnostics.rotational_physics import OrderHypothesis

# ===========================================================================
# OrderMatchAccumulator computed properties
# ===========================================================================


def _make_accumulator(
    possible: int = 20,
    matched: int = 10,
    matched_points: list | None = None,
    *,
    compliance: float = 1.0,
    rel_error: float = 0.01,
) -> OrderMatchAccumulator:
    """Build an accumulator with sensible defaults for testing."""
    if matched_points is None:
        matched_points = [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=rel_error,
                amp=0.05,
                location="front_left",
                speed_kmh=60.0,
            )
            for _ in range(matched)
        ]
    return OrderMatchAccumulator(
        possible=possible,
        matched=matched,
        matched_amp=[0.05] * matched,
        matched_floor=[0.005] * matched,
        rel_errors=[rel_error] * matched,
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
        compliance=compliance,
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
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.05,
                location="front_left",
                speed_kmh=60.0,
            ),
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.05,
                location="front_right",
                speed_kmh=60.0,
            ),
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.04,
                location="front_left",
                speed_kmh=70.0,
            ),
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
        m = _make_accumulator(
            possible=2,
            matched=2,
            matched_points=[
                OrderMatchObservation(
                    predicted_hz=50.0,
                    matched_hz=50.5,
                    rel_error=0.01,
                    amp=0.05,
                    location="x",
                )
                for _ in range(2)
            ],
        )
        assert m.is_eligible() is False

    def test_is_eligible_false_low_matched(self) -> None:
        m = _make_accumulator(
            possible=20,
            matched=1,
            matched_points=[
                OrderMatchObservation(
                    predicted_hz=50.0,
                    matched_hz=50.5,
                    rel_error=0.01,
                    amp=0.05,
                    location="x",
                ),
            ],
        )
        assert m.is_eligible() is False


class TestAssembleOrderFinding:
    def test_ranking_score_uses_compliance_adjusted_error_denominator(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            order_analysis_module,
            "compute_phase_stats",
            lambda *args, **kwargs: ({}, 1),
        )
        monkeypatch.setattr(
            order_analysis_module,
            "compute_amplitude_and_error_stats",
            lambda *args, **kwargs: (0.02, 0.002, 0.10, 0.9, 0.9),
        )
        monkeypatch.setattr(
            order_analysis_module,
            "compute_matched_speed_phase_evidence",
            lambda *args, **kwargs: (60.0, None, None, {"cruise_fraction": 0.0}, None),
        )
        monkeypatch.setattr(
            order_analysis_module,
            "detect_diffuse_excitation",
            lambda *args, **kwargs: (False, 1.0),
        )
        monkeypatch.setattr(
            order_analysis_module,
            "apply_localization_override",
            lambda **kwargs: (0.40, False),
        )
        monkeypatch.setattr(
            order_analysis_module,
            "compute_order_confidence",
            lambda **kwargs: 0.75,
        )
        monkeypatch.setattr(
            "vibesensor.use_cases.diagnostics.location_analysis._location_speedbin_summary",
            lambda *args, **kwargs: ("", None),
        )

        hypothesis = OrderHypothesis(
            key="wheel_1x",
            suspected_source=VibrationSource.WHEEL_TIRE,
            order_label_base="wheel",
            order=1,
            path_compliance=1.0,
        )
        context = OrderFindingBuildContext(
            effective_match_rate=0.8,
            focused_speed_band=None,
            per_location_dominant=False,
            match_rate=0.8,
            min_match_rate=0.5,
            constant_speed=False,
            steady_speed=False,
            connected_locations={"front_left"},
            lang="en",
        )

        score_low, finding_low = order_analysis_module.assemble_order_finding(
            hypothesis,
            _make_accumulator(rel_error=0.10, compliance=1.0),
            context=context,
        )
        score_high, finding_high = order_analysis_module.assemble_order_finding(
            hypothesis,
            _make_accumulator(rel_error=0.10, compliance=4.0),
            context=context,
        )

        low_error_factor = 1.0 - min(1.0, 0.10 / (0.25 * 1.0))
        high_error_factor = 1.0 - min(1.0, 0.10 / (0.25 * 4.0))
        expected_ratio = high_error_factor / low_error_factor

        assert score_high > score_low
        assert score_high == pytest.approx(score_low * expected_ratio, rel=1e-6)
        assert finding_low.ranking_score == pytest.approx(score_low, rel=1e-6)
        assert finding_high.ranking_score == pytest.approx(score_high, rel=1e-6)


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
