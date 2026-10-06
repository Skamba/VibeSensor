"""Direct behavior tests for order confidence scoring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import ALL_WHEEL_SENSORS, wheel_hz
from test_support.synthetic_samples import make_sample

from vibesensor.analysis.orders.heuristics import detect_diffuse_excitation
from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.analysis.orders.statistics import (
    compute_matched_speed_phase_evidence,
    compute_phase_stats,
)
from vibesensor.analysis.orders.statistics import (
    compute_order_confidence as _compute_order_confidence,
)
from vibesensor.analysis.speed_profile_helpers import speed_constancy, speed_steadiness
from vibesensor.domain.order_match import OrderMatchObservation

# The most one small step of any graded input may move the score
# (0.01 of a rate, score or dominance; 0.05 km/h; 0.05 of an amplitude ratio).
_MAX_STEP = 0.05


def _steps(scores: list[float]) -> list[float]:
    return [after - before for before, after in zip(scores, scores[1:], strict=False)]


def _grid(low: float, high: float, step: float) -> list[float]:
    return [low + i * step for i in range(round((high - low) / step) + 1)]


class TestComputeOrderConfidence:
    """Direct unit tests for _compute_order_confidence."""

    _DEFAULTS: dict[str, Any] = {
        "effective_match_rate": 0.60,
        "min_match_rate": 0.25,
        "error_score": 0.80,
        "corr_val": 0.50,
        "snr_score": 0.60,
        "absolute_strength_db": 20.0,
        "localization_confidence": 0.70,
        "weak_spatial_separation": False,
        "dominance_ratio": 2.0,
        "constancy": 0.0,
        "steadiness": 0.0,
        "matched": 30,
        "corroborating_locations": 2,
        "phases_with_evidence": 2,
        "diffuse_penalty": 1.0,
        "n_connected_locations": 3,
        "no_wheel_sensors": False,
        "path_compliance": 1.0,
    }

    @classmethod
    def _call(cls, **overrides: Any) -> float:
        return _compute_order_confidence(**{**cls._DEFAULTS, **overrides})

    def test_bonuses_do_not_lift_a_negligible_order_over_the_cap(self) -> None:
        """Road noise matched on every sensor in every phase stays at the cap."""
        cap = ORDER_CONFIDENCE_SETTINGS.weak_confidence_cap
        noise = self._call(
            absolute_strength_db=6.4,
            effective_match_rate=0.9,
            error_score=0.9,
            corr_val=0.95,
            localization_confidence=1.0,
            corroborating_locations=4,
            phases_with_evidence=3,
            n_connected_locations=4,
        )
        assert noise == pytest.approx(cap)
        penalized = self._call(absolute_strength_db=6.4, weak_spatial_separation=True)
        assert penalized < cap

    @pytest.mark.parametrize(
        ("normal_kw", "penalty_kw"),
        [
            pytest.param(
                {"weak_spatial_separation": False},
                {"weak_spatial_separation": True},
                id="weak_spatial_separation",
            ),
            pytest.param({"constancy": 0.0}, {"constancy": 1.0}, id="constant_speed"),
            pytest.param({"steadiness": 0.0}, {"steadiness": 1.0}, id="steady_speed"),
            pytest.param({"diffuse_penalty": 1.0}, {"diffuse_penalty": 0.75}, id="diffuse"),
            pytest.param(
                {"n_connected_locations": 3},
                {"n_connected_locations": 1},
                id="single_sensor",
            ),
            pytest.param(
                {"absolute_strength_db": 25.0},
                {"absolute_strength_db": 12.0},
                id="light_strength_band",
            ),
            pytest.param({"matched": 30}, {"matched": 5}, id="few_matched_samples"),
        ],
    )
    def test_penalty_reduces_confidence(
        self,
        normal_kw: dict[str, Any],
        penalty_kw: dict[str, Any],
    ) -> None:
        assert self._call(**penalty_kw) < self._call(**normal_kw)

    _SPREAD: dict[str, Any] = {
        "weak_spatial_separation": True,
        "localization_confidence": 0.05,
        "dominance_ratio": 1.0,
    }
    # An engine/driveline order with no dominant corner whose own evidence is
    # established: heard often, on frequency, at several sensors.
    _ZONE: dict[str, Any] = {
        **_SPREAD,
        "zone_source": True,
        "zone_match_rate": 0.9,
        "error_score": 0.9,
        "corroborating_locations": 3,
    }

    @pytest.mark.parametrize(
        "profile",
        [
            pytest.param({}, id="wheel-at-a-corner"),
            pytest.param(_SPREAD, id="spread-wheel"),
            pytest.param(_ZONE, id="engine-zone"),
        ],
    )
    def test_half_a_db_moves_confidence_only_a_little(self, profile: dict[str, Any]) -> None:
        scores = [
            self._call(**{**profile, "absolute_strength_db": tenths / 10})
            for tenths in range(40, 300, 5)
        ]
        steps = _steps(scores)
        assert min(steps) >= 0.0
        assert max(steps) <= 0.08

    def test_a_light_vibration_scores_no_higher_for_nearing_the_moderate_band(self) -> None:
        # Under 16 dB nothing ramps: a wheel order there is not Strong on strength.
        assert self._call(absolute_strength_db=15.9) == self._call(absolute_strength_db=12.5)

    def test_an_established_zone_scores_like_a_clearly_dominant_corner(self) -> None:
        located = {**self._ZONE, "zone_source": False, "weak_spatial_separation": False}
        located["localization_confidence"] = ORDER_CONFIDENCE_SETTINGS.zone_localization_confidence
        assert self._call(**self._ZONE, absolute_strength_db=19.0) == pytest.approx(
            self._call(**located, absolute_strength_db=19.0)
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"absolute_strength_db": 13.0}, id="faint"),
            pytest.param({"zone_match_rate": 0.4}, id="patchy"),
            pytest.param({"error_score": 0.5}, id="off-frequency"),
            pytest.param({"corroborating_locations": 1}, id="one-sensor"),
            pytest.param({"wheel_shared_fraction": 0.5}, id="wheel-alias"),
        ],
    )
    def test_a_zone_without_its_own_evidence_keeps_the_corner_penalties(
        self, overrides: dict[str, Any]
    ) -> None:
        zone = {**self._ZONE, "absolute_strength_db": 22.0, **overrides}
        assert self._call(**zone) == self._call(**{**zone, "zone_source": False})

    # Each graded input swept across its old step edge, in small steps: the
    # score moves one way, by a little per step, and the full change is kept.
    @pytest.mark.parametrize(
        ("profile", "name", "values", "direction"),
        [
            pytest.param(_ZONE, "zone_match_rate", _grid(0.30, 0.60, 0.01), 1, id="zone-rate"),
            pytest.param(_ZONE, "error_score", _grid(0.40, 0.70, 0.01), 1, id="zone-error"),
            pytest.param(
                _ZONE, "wheel_shared_fraction", _grid(0.30, 0.60, 0.01), -1, id="zone-alias"
            ),
            pytest.param(
                {"n_connected_locations": 2},
                "localization_confidence",
                _grid(0.0, 0.70, 0.01),
                1,
                id="two-sensor-localisation",
            ),
            pytest.param({}, "effective_match_rate", _grid(0.25, 0.60, 0.01), 1, id="presence"),
        ],
    )
    def test_a_graded_input_moves_confidence_a_little_per_step(
        self, profile: dict[str, Any], name: str, values: list[float], direction: int
    ) -> None:
        scores = [self._call(**{**profile, name: value}) for value in values]
        steps = [direction * step for step in _steps(scores)]
        assert min(steps) >= -1e-12
        assert max(steps) <= _MAX_STEP
        assert direction * (scores[-1] - scores[0]) > 0.05

    def test_an_order_heard_just_often_enough_is_at_most_weak(self) -> None:
        cap = ORDER_CONFIDENCE_SETTINGS.weak_confidence_cap
        assert self._call(effective_match_rate=0.25, error_score=1.0, corr_val=1.0) <= cap
        # Once heard often enough, the minimum no longer limits the score.
        settled = 0.25 + ORDER_CONFIDENCE_SETTINGS.presence_ramp
        assert self._call(effective_match_rate=settled) == self._call(
            effective_match_rate=settled, min_match_rate=0.0
        )

    @pytest.mark.parametrize(
        ("edge", "no_wheel"),
        [
            pytest.param(1.20, False, id="two-locations"),
            pytest.param(1.44, False, id="four-locations"),
            pytest.param(None, True, id="no-wheel-sensors"),
        ],
    )
    def test_dominance_moves_confidence_a_little_per_step(
        self, edge: float | None, no_wheel: bool
    ) -> None:
        def score(dominance: float) -> float:
            return self._call(
                dominance_ratio=dominance,
                weak_spatial_separation=no_wheel or dominance < (edge or 0.0),
                weak_separation_edge=edge,
                no_wheel_sensors=no_wheel,
                localization_confidence=0.3,
            )

        scores = [score(dominance) for dominance in _grid(0.95, 2.0, 0.01)]
        assert min(_steps(scores)) >= -1e-12
        assert max(_steps(scores)) <= _MAX_STEP
        # The full span of the old steps is kept: uniform 0.70 to none (or to
        # 0.90 for a cabin hotspot without wheel sensors).
        expected = 0.90 / 0.70 if no_wheel else 1.0 / 0.70
        assert scores[-1] / scores[0] == pytest.approx(expected)

    @pytest.mark.parametrize("name", ["constancy", "steadiness"])
    def test_speed_grades_scale_the_score_linearly(self, name: str) -> None:
        scores = [self._call(**{name: grade}) for grade in _grid(0.0, 1.0, 0.05)]
        assert max(abs(step) for step in _steps(scores)) <= _MAX_STEP
        assert scores[-1] < scores[0]


@pytest.mark.parametrize(
    ("grade", "values", "make"),
    [
        pytest.param(
            speed_steadiness, _grid(1.5, 3.5, 0.05), lambda v: (v, 5.0), id="steady-stddev"
        ),
        pytest.param(
            speed_steadiness, _grid(6.0, 14.0, 0.05), lambda v: (1.0, v), id="steady-range"
        ),
        pytest.param(speed_constancy, _grid(0.3, 1.2, 0.05), lambda v: (v,), id="constant"),
    ],
)
def test_speed_grades_ease_out_past_the_limits(
    grade: Callable[..., float], values: list[float], make: Callable[[float], tuple]
) -> None:
    grades = [grade(*make(value)) for value in values]
    assert grades[0] == 1.0
    assert grades[-1] == 0.0
    assert all(step <= 0.0 for step in _steps(grades))
    assert max(-step for step in _steps(grades)) <= 0.1 + 1e-9


_WHEELS = ("front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel")


def _diffuse(
    *, amp_ratio: float = 1.0, rate_range: float = 0.0, mean_rate: float = 0.6
) -> tuple[bool, float]:
    rates = (mean_rate + rate_range / 2, mean_rate - rate_range / 2, mean_rate, mean_rate)
    points = [
        OrderMatchObservation(
            predicted_hz=10.0,
            matched_hz=10.0,
            rel_error=0.0,
            amp=amp_ratio if location == _WHEELS[0] else 1.0,
            location=location,
        )
        for location in _WHEELS
    ]
    return detect_diffuse_excitation(
        set(_WHEELS),
        dict.fromkeys(_WHEELS, 1000),
        {location: round(rate * 1000) for location, rate in zip(_WHEELS, rates, strict=True)},
        points,
    )


@pytest.mark.parametrize(
    ("knob", "values"),
    [
        pytest.param("amp_ratio", _grid(1.5, 3.5, 0.05), id="amplitude-ratio"),
        pytest.param("rate_range", _grid(0.0, 0.40, 0.01), id="match-rate-range"),
        pytest.param("mean_rate", _grid(0.25, 0.0, -0.01)[:-1], id="mean-match-rate"),
    ],
)
def test_the_diffuse_penalty_eases_out_past_each_edge(knob: str, values: list[float]) -> None:
    results = [_diffuse(**{knob: value}) for value in values]
    penalties = [penalty for _flag, penalty in results]
    full = 0.85 - 0.04 * len(_WHEELS)
    assert results[0] == (True, pytest.approx(full))
    assert results[-1] == (False, 1.0)
    assert all(step >= -1e-12 for step in _steps(penalties))
    # A penalty step of 0.035 is under 0.04 of a Strong score.
    assert max(_steps(penalties)) <= 0.035


def _hotspot_run(dominance: float) -> list[dict[str, Any]]:
    """A wheel order at four wheel sensors, clearest at front-left by *dominance*.

    Front-left hears it in 3 of 10 windows, the other wheels in 2 of 10: too
    seldom overall, but often enough at front-left alone, so the per-location
    evidence pins it to that wheel (``per_location_dominant``).
    """
    samples = []
    for i in range(60):
        speed = 50.0 + i
        for sensor in ALL_WHEEL_SENSORS:
            peaks = [{"hz": 200.0, "amp": 0.004}]
            if sensor == "front-left" and i % 10 in (0, 3, 6):
                peaks.insert(0, {"hz": wheel_hz(speed), "amp": 0.03 * dominance})
            elif sensor != "front-left" and i % 10 in (1, 5):
                peaks.insert(0, {"hz": wheel_hz(speed), "amp": 0.03})
            samples.append(
                make_sample(
                    t_s=float(i),
                    speed_kmh=speed,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=24.0 if sensor == "front-left" else 18.0,
                    strength_floor_amp_g=0.004,
                )
            )
    return samples


def test_a_clearer_hotspot_never_lowers_the_confidence() -> None:
    # Swept across the dominance edge where four wheel sensors stop calling
    # the hotspot weakly separated (1.44): the per-location evidence already
    # declared it separated, so no spread penalty applies on either side of
    # the edge, nor eases out past it. Only the strength term moves the score.
    findings = []
    for dominance in _grid(1.30, 1.70, 0.02):
        summary = run_analysis(_hotspot_run(dominance))
        wheel = next(f for f in summary["findings"] if f["suspected_source"] == "wheel/tire")
        assert wheel["strongest_location"] == "front-left"
        assert wheel["dominance_ratio"] == pytest.approx(dominance)
        findings.append(wheel)
    assert {f["location_hotspot"]["weak_spatial_separation"] for f in findings} == {False}
    steps = _steps([f["confidence"] for f in findings])
    assert min(steps) >= -1e-9
    assert max(steps) <= 0.003


def _points(phase: str, speed_kmh: float, amp: float, count: int) -> list[OrderMatchObservation]:
    return [
        OrderMatchObservation(
            predicted_hz=10.0,
            matched_hz=10.0,
            rel_error=0.0,
            amp=amp,
            location="front_left_wheel",
            speed_kmh=speed_kmh,
            phase=phase,
        )
        for _ in range(count)
    ]


def test_braking_is_slowing_down_not_one_more_phase_for_the_bonus() -> None:
    # Before braking had its own label, these spectra were all "deceleration":
    # splitting them may not turn two phases into three.
    _per_phase, phases = compute_phase_stats(
        True,
        {"cruise": 20, "deceleration": 10, "braking": 10},
        {"cruise": 10, "deceleration": 5, "braking": 5},
        min_match_rate=0.25,
    )
    assert phases == 2


def test_braking_matches_weigh_on_the_speed_like_other_slowing_down() -> None:
    # At 60 km/h the order is 0.03 g at a cruise and 0.12 g while slowing down;
    # at 100 km/h it is 0.05 g at a cruise. A match while slowing down weighs
    # less than one at a cruise, whether the car slowed by lifting off or on
    # the brakes, so 100 km/h is where it shakes hardest.
    def band(phase: str) -> str | None:
        points = [
            *_points("cruise", 100.0, 0.05, 5),
            *_points("cruise", 60.0, 0.03, 5),
            *_points(phase, 60.0, 0.12, 5),
        ]
        evidence = compute_matched_speed_phase_evidence(
            points, focused_speed_band=None, hotspot_speed_band=""
        )
        return evidence.strongest_speed_band

    assert band("braking") == band("deceleration") == "100-110 km/h"
