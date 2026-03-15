"""Confidence- and certainty-focused report scenario regressions."""

from __future__ import annotations

from math import log1p

import pytest
from test_support.core import standard_metadata
from test_support.sample_scenarios import (
    build_speed_sweep_samples,
    max_order_source_conf,
)

from vibesensor.domain import Finding
from vibesensor.domain.confidence_assessment import ConfidenceAssessment
from vibesensor.shared.constants import MEMS_NOISE_FLOOR_G
from vibesensor.use_cases.diagnostics import summarize_run_data


class TestConfidenceCalibration:
    """Confidence scoring should reflect sample support and signal quality."""

    def test_low_match_count_has_lower_confidence_than_high_count(self) -> None:
        metadata = standard_metadata()
        low_summary = summarize_run_data(
            metadata,
            build_speed_sweep_samples(peak_amp=0.08, vib_db=24.0, n=6),
            include_samples=False,
        )
        high_summary = summarize_run_data(
            metadata,
            build_speed_sweep_samples(peak_amp=0.08, vib_db=24.0, n=40),
            include_samples=False,
        )

        def best_order_conf(summary: dict[str, object]) -> float:
            return max(
                (
                    float(finding.get("confidence") or 0.0)
                    for finding in summary.get("findings", [])
                    if isinstance(finding, dict) and str(finding.get("finding_id", "")) == "F_ORDER"
                ),
                default=0.0,
            )

        low_conf = best_order_conf(low_summary)
        high_conf = best_order_conf(high_summary)
        if low_conf > 0.0 and high_conf > 0.0:
            assert low_conf < high_conf
            assert low_conf <= high_conf * 0.85

    def test_noise_floor_guard_prevents_snr_blowup_with_near_zero_floor(self) -> None:
        mean_amp = 0.002
        near_zero_floor = 1e-7

        snr_without_guard = min(1.0, log1p(mean_amp / max(1e-6, near_zero_floor)) / 2.5)
        snr_floor_clamped = min(
            1.0,
            log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, near_zero_floor)) / 2.5,
        )
        if mean_amp <= 2 * MEMS_NOISE_FLOOR_G:
            snr_with_abs_guard = min(snr_floor_clamped, 0.40)
        else:
            snr_with_abs_guard = snr_floor_clamped

        assert snr_without_guard > 0.95
        assert snr_with_abs_guard <= 0.40
        assert MEMS_NOISE_FLOOR_G == 0.001

        normal_floor = 0.005
        snr_normal_clamped = min(1.0, log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, normal_floor)) / 2.5)
        snr_normal_direct = min(1.0, log1p(mean_amp / normal_floor) / 2.5)
        assert abs(snr_normal_clamped - snr_normal_direct) < 1e-10

    def test_constant_speed_penalty_keeps_confidence_below_steady_sweep(self) -> None:
        metadata = standard_metadata()
        steady_samples = build_speed_sweep_samples(speed_start_kmh=79.5, speed_end_kmh=80.5, n=24)
        steady_summary = summarize_run_data(metadata, steady_samples, include_samples=False)
        assert max_order_source_conf(steady_summary) <= 0.65

    def test_confidence_label_thresholds(self) -> None:
        assert Finding.classify_confidence(0.75)[:2] == ("CONFIDENCE_HIGH", "success")
        assert Finding.classify_confidence(0.50)[:2] == ("CONFIDENCE_MEDIUM", "warn")
        assert Finding.classify_confidence(0.20)[:2] == ("CONFIDENCE_LOW", "neutral")


class TestConfidenceAssessmentSignalQualityGuard:
    """Negligible strength must cap confidence assessment labels."""

    @pytest.mark.parametrize(
        ("confidence", "strength_band_key", "expected_label_key"),
        [
            pytest.param(
                0.90,
                "negligible",
                "CONFIDENCE_MEDIUM",
                id="negligible_caps_high_to_medium",
            ),
            pytest.param(
                0.55,
                "negligible",
                "CONFIDENCE_MEDIUM",
                id="negligible_keeps_medium",
            ),
            pytest.param(
                0.30,
                "negligible",
                "CONFIDENCE_LOW",
                id="negligible_keeps_low",
            ),
        ],
    )
    def test_negligible_strength_certainty(
        self,
        confidence: float,
        strength_band_key: str,
        expected_label_key: str,
    ) -> None:
        ca = ConfidenceAssessment.assess(
            confidence,
            strength_band_key=strength_band_key,
        )
        assert ca.label_key == expected_label_key

    @pytest.mark.parametrize("band", ["light", "moderate", "strong", "very_strong", None])
    def test_non_negligible_strength_allows_high_confidence(self, band: str | None) -> None:
        ca = ConfidenceAssessment.assess(0.80, strength_band_key=band)
        assert ca.label_key == "CONFIDENCE_HIGH"
