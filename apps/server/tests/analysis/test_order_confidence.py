"""Direct behavior tests for order confidence scoring."""

from __future__ import annotations

from typing import Any

import pytest

from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.analysis.orders.statistics import (
    compute_order_confidence as _compute_order_confidence,
)


class TestComputeOrderConfidence:
    """Direct unit tests for _compute_order_confidence."""

    _DEFAULTS: dict[str, Any] = {
        "effective_match_rate": 0.60,
        "error_score": 0.80,
        "corr_val": 0.50,
        "snr_score": 0.60,
        "absolute_strength_db": 20.0,
        "localization_confidence": 0.70,
        "weak_spatial_separation": False,
        "dominance_ratio": 2.0,
        "constant_speed": False,
        "steady_speed": False,
        "matched": 30,
        "corroborating_locations": 2,
        "phases_with_evidence": 2,
        "is_diffuse_excitation": False,
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
        cap = ORDER_CONFIDENCE_SETTINGS.negligible_strength_confidence_cap
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
            pytest.param(
                {"constant_speed": False},
                {"constant_speed": True},
                id="constant_speed",
            ),
            pytest.param(
                {"is_diffuse_excitation": False},
                {"is_diffuse_excitation": True, "diffuse_penalty": 0.75},
                id="diffuse_excitation",
            ),
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
        "spread_zone_source": True,
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
        steps = [after - before for before, after in zip(scores, scores[1:], strict=False)]
        assert min(steps) >= 0.0
        assert max(steps) <= 0.08

    def test_a_light_vibration_scores_no_higher_for_nearing_the_moderate_band(self) -> None:
        # Under 16 dB nothing ramps: a wheel order there is not Strong on strength.
        assert self._call(absolute_strength_db=15.9) == self._call(absolute_strength_db=12.5)

    def test_an_established_zone_scores_like_a_clearly_dominant_corner(self) -> None:
        located = {**self._ZONE, "spread_zone_source": False, "weak_spatial_separation": False}
        located["localization_confidence"] = ORDER_CONFIDENCE_SETTINGS.zone_localization_confidence
        assert self._call(**self._ZONE, absolute_strength_db=19.0) == pytest.approx(
            self._call(**located, absolute_strength_db=19.0)
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"absolute_strength_db": 13.0}, id="faint"),
            pytest.param({"zone_match_rate": 0.3}, id="patchy"),
            pytest.param({"error_score": 0.4}, id="off-frequency"),
            pytest.param({"corroborating_locations": 1}, id="one-sensor"),
        ],
    )
    def test_a_zone_without_its_own_evidence_keeps_the_corner_penalties(
        self, overrides: dict[str, Any]
    ) -> None:
        zone = {**self._ZONE, "absolute_strength_db": 22.0, **overrides}
        assert self._call(**zone) == self._call(**{**zone, "spread_zone_source": False})
