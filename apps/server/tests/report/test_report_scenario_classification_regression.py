"""Classification- and labeling-focused report scenario regressions."""

from __future__ import annotations

import pytest

from vibesensor.analysis.findings_persistent import _classify_peak_type
from vibesensor.analysis.helpers import _location_label
from vibesensor.peak_classification import classify_peak_hz
from vibesensor.strength_bands import bucket_for_strength


class TestStrengthBandsAlignment:
    """Strength band thresholds should stay aligned across report layers."""

    @pytest.mark.parametrize(
        ("db_val", "expected_bucket"),
        [
            pytest.param(0.0, "l0", id="l0_at_0"),
            pytest.param(5.0, "l0", id="l0_at_5"),
            pytest.param(7.9, "l0", id="l0_at_7.9"),
            pytest.param(8.0, "l1", id="l1_at_8"),
            pytest.param(15.9, "l1", id="l1_at_15.9"),
            pytest.param(16.0, "l2", id="l2_at_16"),
            pytest.param(25.9, "l2", id="l2_at_25.9"),
            pytest.param(26.0, "l3", id="l3_at_26"),
            pytest.param(35.9, "l3", id="l3_at_35.9"),
            pytest.param(36.0, "l4", id="l4_at_36"),
            pytest.param(45.9, "l4", id="l4_at_45.9"),
            pytest.param(46.0, "l5", id="l5_at_46"),
            pytest.param(100.0, "l5", id="l5_at_100"),
        ],
    )
    def test_bucket_for_strength(self, db_val: float, expected_bucket: str) -> None:
        assert bucket_for_strength(db_val) == expected_bucket


class TestPeakClassification:
    """Peak classification edge cases including baseline noise."""

    @pytest.mark.parametrize(
        ("presence", "burstiness", "kwargs", "expected"),
        [
            pytest.param(0.50, 2.0, {}, "patterned", id="patterned"),
            pytest.param(0.25, 3.5, {}, "persistent", id="persistent"),
            pytest.param(0.05, 1.0, {}, "transient", id="transient"),
            pytest.param(0.50, 6.0, {}, "transient", id="high_burstiness_transient"),
            pytest.param(
                0.80,
                1.5,
                {"snr": 1.0},
                "baseline_noise",
                id="baseline_noise_low_snr",
            ),
            pytest.param(
                0.70,
                1.5,
                {"snr": 5.0, "spatial_uniformity": 0.90},
                "baseline_noise",
                id="baseline_noise_high_uniformity",
            ),
            pytest.param(
                0.70,
                1.5,
                {"snr": 5.0, "spatial_uniformity": 0.50},
                "patterned",
                id="not_baseline_if_snr_high",
            ),
        ],
    )
    def test_classify_peak_type(
        self,
        presence: float,
        burstiness: float,
        kwargs: dict[str, float],
        expected: str,
    ) -> None:
        assert _classify_peak_type(presence, burstiness, **kwargs) == expected


class TestOverlapDetection:
    """Wheel and engine overlap labeling should remain stable."""

    def test_wheel2_eng1_overlap_detection(self) -> None:
        result = classify_peak_hz(
            peak_hz=20.0,
            speed_mps=80.0 / 3.6,
            settings={
                "tire_width_mm": 285.0,
                "tire_aspect_pct": 30.0,
                "rim_in": 21.0,
                "tire_deflection_factor": 1.0,
                "final_drive_ratio": 3.08,
                "current_gear_ratio": 0.64,
                "wheel_bandwidth_pct": 5.0,
                "driveshaft_bandwidth_pct": 4.5,
                "engine_bandwidth_pct": 5.2,
                "speed_uncertainty_pct": 1.0,
                "tire_diameter_uncertainty_pct": 1.0,
                "final_drive_uncertainty_pct": 0.1,
                "gear_uncertainty_pct": 0.2,
                "min_abs_band_hz": 0.2,
                "max_band_half_width_pct": 6.0,
            },
        )
        assert result.get("key") == "wheel2_eng1"


class TestLocationLabel:
    """Structured locations should drive labels before free-form names."""

    @pytest.mark.parametrize(
        ("sample", "expected"),
        [
            pytest.param(
                {"client_name": "My sensor", "location": "front_left_wheel"},
                "Front Left Wheel",
                id="structured_location_preferred",
            ),
            pytest.param(
                {"client_name": "Rear Axle Custom"},
                "Rear Axle Custom",
                id="fallback_to_client_name",
            ),
            pytest.param(
                {"location": "custom_spot"},
                "custom_spot",
                id="unknown_location_code_used_raw",
            ),
        ],
    )
    def test_location_label(self, sample: dict[str, str], expected: str) -> None:
        assert _location_label(sample) == expected
