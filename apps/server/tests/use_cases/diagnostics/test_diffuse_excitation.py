"""Direct behavior tests for diffuse excitation detection."""

from __future__ import annotations

from vibesensor.domain import OrderMatchObservation
from vibesensor.use_cases.diagnostics.orders.heuristics import (
    detect_diffuse_excitation as _detect_diffuse_excitation,
)


class TestDetectDiffuseExcitation:
    """Direct unit tests for _detect_diffuse_excitation."""

    def test_single_sensor_returns_not_diffuse(self) -> None:
        is_diff, penalty = _detect_diffuse_excitation(
            connected_locations={"front_left"},
            possible_by_location={"front_left": 20},
            matched_by_location={"front_left": 15},
            matched_points=[
                OrderMatchObservation(
                    predicted_hz=50.0,
                    matched_hz=50.5,
                    rel_error=0.01,
                    amp=0.1,
                    location="front_left",
                )
            ]
            * 15,
        )
        assert not is_diff
        assert penalty == 1.0

    def test_uniform_rates_uniform_amplitude_is_diffuse(self) -> None:
        locs = {"front_left", "front_right", "rear"}
        possible = dict.fromkeys(locs, 30)
        matched = dict.fromkeys(locs, 20)
        pts = [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.05,
                location=loc,
            )
            for loc in locs
            for _ in range(20)
        ]
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert is_diff, "Uniform rates + uniform amplitude should be diffuse"
        assert penalty < 1.0

    def test_dominant_amplitude_is_not_diffuse(self) -> None:
        locs = {"front_left", "rear"}
        possible = {"front_left": 20, "rear": 20}
        matched = {"front_left": 15, "rear": 14}
        pts = [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.30,
                location="front_left",
            )
        ] * 15 + [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.05,
                location="rear",
            ),
        ] * 14
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Strong amplitude dominance should NOT be diffuse"

    def test_insufficient_samples_per_location(self) -> None:
        locs = {"front_left", "rear"}
        possible = {"front_left": 2, "rear": 2}
        matched = {"front_left": 2, "rear": 2}
        pts = [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.05,
                location="front_left",
            )
        ] * 2
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Too few samples should not trigger diffuse"

    def test_empty_matched_points(self) -> None:
        locs = {"a", "b"}
        is_diff, penalty = _detect_diffuse_excitation(
            locs,
            {"a": 20, "b": 20},
            {"a": 15, "b": 15},
            [],
        )
        assert isinstance(is_diff, bool)
        assert penalty <= 1.0
