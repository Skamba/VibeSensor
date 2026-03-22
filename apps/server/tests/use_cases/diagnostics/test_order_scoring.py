"""Focused tests for order-finding scoring independent from final DomainFinding assembly."""

from __future__ import annotations

import pytest

import vibesensor.use_cases.diagnostics.order_scoring as order_scoring_module
from vibesensor.domain import OrderMatchObservation, VibrationSource
from vibesensor.use_cases.diagnostics.order_matching import OrderMatchAccumulator
from vibesensor.use_cases.diagnostics.order_scoring import (
    OrderFindingBuildContext,
    score_order_finding,
)
from vibesensor.use_cases.diagnostics.rotational_physics import OrderHypothesis


def _make_accumulator(
    possible: int = 20,
    matched: int = 10,
    *,
    compliance: float = 1.0,
    rel_error: float = 0.01,
) -> OrderMatchAccumulator:
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


def test_ranking_score_uses_compliance_adjusted_error_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        order_scoring_module,
        "compute_phase_stats",
        lambda *args, **kwargs: ({}, 1),
    )
    monkeypatch.setattr(
        order_scoring_module,
        "compute_amplitude_and_error_stats",
        lambda *args, **kwargs: (0.02, 0.002, 0.10, 0.9, 0.9),
    )
    monkeypatch.setattr(
        order_scoring_module,
        "summarize_order_match_locations",
        lambda *args, **kwargs: ("", None),
    )
    monkeypatch.setattr(
        order_scoring_module,
        "detect_diffuse_excitation",
        lambda *args, **kwargs: (False, 1.0),
    )
    monkeypatch.setattr(
        order_scoring_module,
        "apply_localization_override",
        lambda **kwargs: (0.40, False),
    )
    monkeypatch.setattr(
        order_scoring_module,
        "compute_order_confidence",
        lambda **kwargs: 0.75,
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

    score_low = score_order_finding(
        hypothesis,
        _make_accumulator(rel_error=0.10, compliance=1.0),
        context=context,
    )
    score_high = score_order_finding(
        hypothesis,
        _make_accumulator(rel_error=0.10, compliance=4.0),
        context=context,
    )

    low_error_factor = 1.0 - min(1.0, 0.10 / (0.25 * 1.0))
    high_error_factor = 1.0 - min(1.0, 0.10 / (0.25 * 4.0))
    expected_ratio = high_error_factor / low_error_factor

    assert score_high.ranking_score > score_low.ranking_score
    assert score_high.ranking_score == pytest.approx(
        score_low.ranking_score * expected_ratio,
        rel=1e-6,
    )
    assert score_low.confidence == pytest.approx(0.75)
    assert score_high.confidence == pytest.approx(0.75)
