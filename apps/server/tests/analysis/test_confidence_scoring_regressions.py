# ruff: noqa: E402
from __future__ import annotations

"""Confidence and scoring regressions:
- Ranking score error denominator uses compliance (matches confidence formula)
- _suppress_engine_aliases filters before slicing (no lost valid findings)
- Single-sensor confidence no longer triple-penalised
- Persistent peak negligible cap aligned to 0.40 (matches order cap)
"""


import inspect

import pytest

from vibesensor.analysis.order_analysis import (
    compute_order_confidence as _compute_order_confidence,
)
from vibesensor.analysis.order_analysis import (
    suppress_engine_aliases as _suppress_engine_aliases,
)

# ---------------------------------------------------------------------------
# Bug 1: ranking_score error denominator must use compliance
# ---------------------------------------------------------------------------


class TestRankingScoreErrorDenominator:
    """The ranking_score error term must use the same compliance-adjusted
    denominator as the confidence formula (0.25 * compliance).
    """

    def test_no_hardcoded_denominator_in_ranking(self) -> None:
        """Source must not hardcode 0.5 denominator for ranking error.

        The ranking_score computation lives in ``assemble_order_finding``
        in ``order_analysis``; verify it there.
        """
        from vibesensor.analysis.order_analysis import assemble_order_finding

        src = inspect.getsource(assemble_order_finding)
        # Old code had a hardcoded 0.5 denominator; new code derives from compliance.
        assert "mean_rel_err / 0.5" not in src, (
            "ranking_score must not hardcode error denominator to 0.5"
        )
        assert "match.compliance" in src, (
            "ranking_score must use a compliance-derived error denominator"
        )


# ---------------------------------------------------------------------------
# Bug 2: _suppress_engine_aliases must filter before slicing
# ---------------------------------------------------------------------------


class TestSuppressEngineAliasesFilterBeforeSlice:
    """Suppressed engine findings must not consume top-5 slots, preventing
    valid findings at position 6+ from being returned.
    """

    def test_valid_finding_not_lost_after_suppression(self) -> None:
        # Build 7 findings: 2 wheel, 3 engine (will be suppressed below
        # ORDER_MIN_CONFIDENCE), 2 driveshaft at end.
        findings: list[tuple[float, dict]] = [
            (
                1.0,
                {
                    "suspected_source": "wheel/tire",
                    "confidence": 0.80,
                    "ranking_score": 1.0,
                },
            ),
            (
                0.9,
                {
                    "suspected_source": "wheel/tire",
                    "confidence": 0.70,
                    "ranking_score": 0.9,
                },
            ),
            # These 3 engine findings will be suppressed below threshold
            (
                0.7,
                {
                    "suspected_source": "engine",
                    "confidence": 0.40,
                    "ranking_score": 0.7,
                },
            ),
            (
                0.6,
                {
                    "suspected_source": "engine",
                    "confidence": 0.38,
                    "ranking_score": 0.6,
                },
            ),
            (
                0.5,
                {
                    "suspected_source": "engine",
                    "confidence": 0.35,
                    "ranking_score": 0.5,
                },
            ),
            # These valid findings must NOT be lost
            (
                0.4,
                {
                    "suspected_source": "driveline",
                    "confidence": 0.55,
                    "ranking_score": 0.4,
                },
            ),
            (
                0.3,
                {
                    "suspected_source": "driveline",
                    "confidence": 0.50,
                    "ranking_score": 0.3,
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        driveline = [f for f in result if f["suspected_source"] == "driveline"]
        assert len(driveline) >= 1, (
            "Driveline findings must not be lost when suppressed engine aliases are filtered out"
        )

    def test_suppressed_engine_below_threshold_excluded(self) -> None:
        findings: list[tuple[float, dict]] = [
            (
                1.0,
                {
                    "suspected_source": "wheel/tire",
                    "confidence": 0.80,
                    "ranking_score": 1.0,
                },
            ),
            (
                0.5,
                {
                    "suspected_source": "engine",
                    "confidence": 0.30,
                    "ranking_score": 0.5,
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        engine = [f for f in result if f["suspected_source"] == "engine"]
        # After suppression: 0.30 * 0.60 = 0.18 < ORDER_MIN_CONFIDENCE (0.25)
        assert len(engine) == 0, "Suppressed engine finding below threshold must be excluded"


# ---------------------------------------------------------------------------
# Bug 3: single-sensor triple-penalty stacking
# ---------------------------------------------------------------------------


class TestSingleSensorNotTriplePenalised:
    """Single-sensor findings must not be triple-penalised by stacking
    localization_confidence + weak_spatial + sensor_count penalties.
    """

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
        the explicit sensor-count scale should NOT stack on top.
        """
        # Call twice: once with n_connected=1, once with n_connected=3
        # (n_connected=3 avoids sensor scale entirely).
        kwargs = {
            "effective_match_rate": 0.70,
            "error_score": 0.80,
            "corr_val": 0.60,
            "snr_score": 0.75,
            "absolute_strength_db": 18.0,
            "localization_confidence": 0.05,  # very low
            "weak_spatial_separation": True,
            "dominance_ratio": 1.0,
            "constant_speed": False,
            "steady_speed": False,
            "matched": 20,
            "corroborating_locations": 1,
            "phases_with_evidence": 1,
            "is_diffuse_excitation": False,
            "diffuse_penalty": 1.0,
        }
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
    frequency.
    """

    def test_persistent_peak_cap_value_in_source(self) -> None:
        """Verify that the negligible-strength cap is 0.40 by testing
        the PeakBin's confidence computation directly, rather than
        inspecting source strings (which break on refactors).

        A persistent/patterned peak with strength below NEGLIGIBLE_STRENGTH_MAX_DB
        must have its confidence capped at 0.40.  The cap of 0.40 is
        intentionally aligned with the order-finding negligible cap so
        that a weak order finding at ~0.37 confidence always suppresses
        persistent peaks at the same frequency.
        """
        from vibesensor.analysis.findings import PeakBin

        # Build a PeakBin with high presence (patterned), low burstiness,
        # decent SNR so it classifies as patterned, but low enough absolute
        # amplitude that peak_strength_db < NEGLIGIBLE_STRENGTH_MAX_DB.
        # Using amps ~0.002g with floor ~0.001g gives SNR ~2 (above
        # baseline threshold) and strength ~6 dB (below negligible ~15 dB).
        peak_bin = PeakBin(
            bin_center=50.0,
            amps=[0.002] * 50,
            floor_vals=[0.001] * 50,
            speed_amp_pairs=[(60.0, 0.002)] * 50,
            loc_counts_for_bin={"front_left": 50},
            speed_bin_counts_for_bin={"60-80": 50},
            phases_for_bin={},
            n_samples=50,
            total_locations={"front_left"},
            total_location_sample_counts={"front_left": 50},
            total_speed_bin_counts={"60-80": 50},
            run_noise_baseline_g=0.001,
            has_phases=False,
        )
        # Must be a persistent or patterned type for the cap to apply
        assert peak_bin.peak_type in ("persistent", "patterned"), (
            f"Expected persistent/patterned but got {peak_bin.peak_type}"
        )
        assert peak_bin.confidence <= 0.40, (
            f"Persistent peak negligible cap must be 0.40, got {peak_bin.confidence}"
        )
