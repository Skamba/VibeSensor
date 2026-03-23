"""Tests for order-matching contracts, finding assembly, and OrderAnalysisSession."""

from __future__ import annotations

import pytest
from test_support.report_helpers import diagnostics_context

import vibesensor.use_cases.diagnostics.orders.finding_builder as order_finding_builder_module
from vibesensor.domain import OrderMatchObservation, VibrationSource
from vibesensor.use_cases.diagnostics.orders.matching import (
    OrderMatchAccumulator,
)
from vibesensor.use_cases.diagnostics.orders.physics import OrderHypothesis
from vibesensor.use_cases.diagnostics.orders.pipeline import (
    OrderAnalysisRequest,
    OrderAnalysisSession,
)
from vibesensor.use_cases.diagnostics.orders.scoring import (
    OrderFindingBuildContext,
    OrderFindingScore,
)
from vibesensor.use_cases.diagnostics.orders.statistics import (
    OrderPhaseEvidence,
    compute_matched_speed_phase_evidence,
)

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
    def test_assemble_order_finding_uses_scoring_contract(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            order_finding_builder_module,
            "compute_matched_speed_phase_evidence",
            lambda *args, **kwargs: OrderPhaseEvidence(
                peak_speed_kmh=60.0,
                speed_window_kmh=(55.0, 65.0),
                strongest_speed_band="60-70 km/h",
                cruise_fraction=0.5,
                phases_detected=("cruise",),
                dominant_phase="cruise",
            ),
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

        score, finding = order_finding_builder_module.assemble_order_finding(
            hypothesis,
            _make_accumulator(rel_error=0.10, compliance=1.0),
            context=context,
            score=OrderFindingScore(
                confidence=0.75,
                ranking_score=0.84,
                absolute_strength_db=31.5,
                mean_floor=0.002,
                mean_relative_error=0.10,
                frequency_correlation=0.9,
                phases_with_evidence=1,
                per_phase_confidence={"cruise": 0.8},
                diffuse_excitation=False,
                weak_spatial_separation=False,
                dominance_ratio=None,
                location_line="front-left hotspot",
                domain_hotspot=None,
                strongest_location="front_left",
                hotspot_speed_band="60-70 km/h",
            ),
        )

        assert score == pytest.approx(0.84)
        assert finding.confidence == pytest.approx(0.75)
        assert finding.ranking_score == pytest.approx(0.84)
        assert finding.strongest_location == "front_left"
        assert finding.strongest_speed_band == "60-70 km/h"
        assert finding.evidence.frequency_correlation == pytest.approx(0.9)
        assert finding.evidence.phase_confidences == (("cruise", 0.8),)


class TestComputeMatchedSpeedPhaseEvidence:
    def test_returns_typed_evidence_object(self) -> None:
        points = [
            OrderMatchObservation(
                predicted_hz=30.0,
                matched_hz=30.1,
                rel_error=0.01,
                amp=0.4,
                location="front_left",
                speed_kmh=62.0,
                phase="cruise",
            ),
            OrderMatchObservation(
                predicted_hz=30.0,
                matched_hz=30.2,
                rel_error=0.02,
                amp=0.2,
                location="front_left",
                speed_kmh=58.0,
                phase="acceleration",
            ),
        ]

        evidence = compute_matched_speed_phase_evidence(
            points,
            focused_speed_band=None,
            hotspot_speed_band="50-60 km/h",
        )

        assert isinstance(evidence, OrderPhaseEvidence)
        assert evidence.peak_speed_kmh == pytest.approx(62.0)
        assert evidence.speed_window_kmh is not None
        assert evidence.speed_window_kmh[0] <= evidence.speed_window_kmh[1]
        assert evidence.strongest_speed_band is not None
        assert evidence.cruise_fraction == pytest.approx(0.5)
        assert evidence.phases_detected == ("acceleration", "cruise")
        assert evidence.dominant_phase is None


# ===========================================================================
# OrderAnalysisSession
# ===========================================================================


class TestOrderAnalysisSession:
    def test_empty_samples(self) -> None:
        session = OrderAnalysisSession(
            OrderAnalysisRequest(
                context=diagnostics_context(),
                samples=[],
                speed_sufficient=True,
                steady_speed=False,
                speed_stddev_kmh=5.0,
                tire_circumference_m=2.0,
                engine_ref_sufficient=False,
                raw_sample_rate_hz=100.0,
                connected_locations=set(),
                lang="en",
            ),
        )
        assert session.analyze() == []

    def test_no_sample_rate_returns_empty(self) -> None:
        session = OrderAnalysisSession(
            OrderAnalysisRequest(
                context=diagnostics_context(),
                samples=[{"speed_kmh": 60.0}],
                speed_sufficient=True,
                steady_speed=False,
                speed_stddev_kmh=5.0,
                tire_circumference_m=2.0,
                engine_ref_sufficient=False,
                raw_sample_rate_hz=None,
                connected_locations=set(),
                lang="en",
            ),
        )
        assert session.analyze() == []

    def test_returns_list_of_findings(self) -> None:
        """Smoke test with minimal matching data."""
        session = OrderAnalysisSession(
            OrderAnalysisRequest(
                context=diagnostics_context(),
                samples=[],
                speed_sufficient=False,
                steady_speed=False,
                speed_stddev_kmh=None,
                tire_circumference_m=None,
                engine_ref_sufficient=False,
                raw_sample_rate_hz=100.0,
                connected_locations=set(),
                lang="en",
            ),
        )
        results = session.analyze()
        assert isinstance(results, list)
