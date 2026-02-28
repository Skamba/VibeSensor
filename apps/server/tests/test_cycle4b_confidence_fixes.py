"""Tests for Cycle 4b confidence/scoring fixes:
- Ranking score error denominator uses compliance (matches confidence formula)
- _suppress_engine_aliases filters before slicing (no lost valid findings)
- Single-sensor confidence no longer triple-penalised
- Persistent peak negligible cap aligned to 0.40 (matches order cap)
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Bug 1: ranking_score error denominator must use compliance
# ---------------------------------------------------------------------------


class TestRankingScoreErrorDenominator:
    """The ranking_score error term must use the same compliance-adjusted
    denominator as the confidence formula (0.25 * compliance)."""

    def test_no_hardcoded_denominator_in_ranking(self) -> None:
        """Source must not hardcode 0.5 denominator for ranking error."""
        import inspect

        from vibesensor.analysis.findings import _build_order_findings

        src = inspect.getsource(_build_order_findings)
        # Old code had a hardcoded 0.5 denominator; new code derives from compliance.
        assert "mean_rel_err / 0.5" not in src, (
            "ranking_score must not hardcode error denominator to 0.5"
        )
        assert "ranking_error_denom" in src, (
            "ranking_score must use a compliance-derived error denominator"
        )


# ---------------------------------------------------------------------------
# Bug 2: _suppress_engine_aliases must filter before slicing
# ---------------------------------------------------------------------------


class TestSuppressEngineAliasesFilterBeforeSlice:
    """Suppressed engine findings must not consume top-5 slots, preventing
    valid findings at position 6+ from being returned."""

    def test_valid_finding_not_lost_after_suppression(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        # Build 7 findings: 2 wheel, 3 engine (will be suppressed below
        # ORDER_MIN_CONFIDENCE), 2 driveshaft at end.
        findings: list[tuple[float, dict]] = [
            (1.0, {
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.80,
                "_ranking_score": 1.0,
            }),
            (0.9, {
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.70,
                "_ranking_score": 0.9,
            }),
            # These 3 engine findings will be suppressed below threshold
            (0.7, {
                "suspected_source": "engine",
                "confidence_0_to_1": 0.40,
                "_ranking_score": 0.7,
            }),
            (0.6, {
                "suspected_source": "engine",
                "confidence_0_to_1": 0.38,
                "_ranking_score": 0.6,
            }),
            (0.5, {
                "suspected_source": "engine",
                "confidence_0_to_1": 0.35,
                "_ranking_score": 0.5,
            }),
            # These valid findings must NOT be lost
            (0.4, {
                "suspected_source": "driveline",
                "confidence_0_to_1": 0.55,
                "_ranking_score": 0.4,
            }),
            (0.3, {
                "suspected_source": "driveline",
                "confidence_0_to_1": 0.50,
                "_ranking_score": 0.3,
            }),
        ]
        result = _suppress_engine_aliases(findings)
        driveline = [f for f in result if f["suspected_source"] == "driveline"]
        assert len(driveline) >= 1, (
            "Driveline findings must not be lost when suppressed engine "
            "aliases are filtered out"
        )

    def test_suppressed_engine_below_threshold_excluded(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        findings: list[tuple[float, dict]] = [
            (1.0, {
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.80,
                "_ranking_score": 1.0,
            }),
            (0.5, {
                "suspected_source": "engine",
                "confidence_0_to_1": 0.30,
                "_ranking_score": 0.5,
            }),
        ]
        result = _suppress_engine_aliases(findings)
        engine = [f for f in result if f["suspected_source"] == "engine"]
        # After suppression: 0.30 * 0.60 = 0.18 < ORDER_MIN_CONFIDENCE (0.25)
        assert len(engine) == 0, (
            "Suppressed engine finding below threshold must be excluded"
        )


# ---------------------------------------------------------------------------
# Bug 3: single-sensor triple-penalty stacking
# ---------------------------------------------------------------------------


class TestSingleSensorNotTriplePenalised:
    """Single-sensor findings must not be triple-penalised by stacking
    localization_confidence + weak_spatial + sensor_count penalties."""

    def test_single_sensor_reasonable_confidence(self) -> None:
        from vibesensor.analysis.findings import _compute_order_confidence

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
        from vibesensor.analysis.findings import _compute_order_confidence

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


# ---------------------------------------------------------------------------
# Bug 4: persistent peak negligible cap aligned to 0.40
# ---------------------------------------------------------------------------


class TestPersistentPeakNegligibleCapAligned:
    """The negligible-strength cap for persistent peaks must be 0.40,
    matching the order-finding cap, so that a weak order finding at
    ~0.37 confidence always suppresses persistent peaks at the same
    frequency."""

    def test_cap_value_in_source(self) -> None:
        import inspect

        import vibesensor.analysis.findings as fmod

        src = inspect.getsource(fmod._build_persistent_peak_findings)
        # The negligible cap must be 0.40, not 0.35
        assert "min(confidence, 0.40)" in src, (
            "Persistent peak negligible cap must be 0.40 to align with order cap"
        )
