"""Classification- and labeling-focused report scenario regressions."""

from __future__ import annotations

import pytest

from vibesensor.use_cases.diagnostics.findings import _classify_peak_type
from vibesensor.use_cases.diagnostics.helpers import _location_label
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
