"""Confidence and scoring regressions:
- Ranking score error denominator uses compliance (matches confidence formula)
- _suppress_engine_aliases filters before slicing (no lost valid findings)
- Single-sensor confidence no longer triple-penalised
- Persistent peak negligible cap aligned to 0.40 (matches order cap)
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.findings import (
    _compute_order_confidence,
)


class TestSingleSensorNotTriplePenalised:
    """Single-sensor findings must not be triple-penalised by stacking
    localization_confidence + weak_spatial + sensor_count penalties."""

    def test_single_sensor_reasonable_confidence(self) -> None:
        # Good evidence on single sensor: high match rate, low error,
        # decent SNR, but single sensor -> forced low localization.
        conf = _compute_order_confidence(
            effective_match_rate=0.80,
            error_score=0.85,
            corr_val=0.70,
            snr_score=0.80,
            absolute_strength_db=20.0,
            localization_confidence=0.05,  # typical single-sensor value
            weak_spatial_separation=True,
            dominance_ratio=None,
            constant_speed=False,
            steady_speed=False,
            matched=25,
            corroborating_locations=1,
            phases_with_evidence=2,
            is_diffuse_excitation=False,
            diffuse_penalty=1.0,
            n_connected_locations=1,
        )
        # Before fix: ~0.715 * 0.80 * 0.85 * base ~ 0.22
        # After fix:  lower stacking, should be higher
        assert conf >= 0.25, (
            f"Single-sensor confidence {conf:.3f} is unreasonably low; "
            f"triple-penalty stacking suspected"
        )

    def test_sensor_scale_not_applied_when_localization_low(self) -> None:
        """When localization_confidence is very low (already heavily penalised),
        the explicit sensor-count scale should NOT stack on top."""
        # Call twice: once with n_connected=1, once with n_connected=3
        # (n_connected=3 avoids sensor scale entirely).
        kwargs = dict(
            effective_match_rate=0.70,
            error_score=0.80,
            corr_val=0.60,
            snr_score=0.75,
            absolute_strength_db=18.0,
            localization_confidence=0.05,  # very low
            weak_spatial_separation=True,
            dominance_ratio=1.0,
            constant_speed=False,
            steady_speed=False,
            matched=20,
            corroborating_locations=1,
            phases_with_evidence=1,
            is_diffuse_excitation=False,
            diffuse_penalty=1.0,
        )
        conf_single = _compute_order_confidence(n_connected_locations=1, **kwargs)
        conf_multi = _compute_order_confidence(n_connected_locations=3, **kwargs)
        # With low localization_confidence, the sensor-count penalty should
        # be gated (not applied), making single ~ multi for this scenario.
        assert conf_single == pytest.approx(conf_multi, abs=0.01), (
            f"With low localization_confidence, sensor-count penalty should "
            f"be gated: single={conf_single:.3f}, multi={conf_multi:.3f}"
        )
