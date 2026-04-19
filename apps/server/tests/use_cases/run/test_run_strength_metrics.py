"""Direct behavior tests for strength metric extraction."""

from __future__ import annotations

import pytest

from vibesensor.shared.boundaries.codecs import strength_peak_payloads
from vibesensor.use_cases.run.sample_strength_metrics import extract_strength_data


class TestExtractStrengthData:
    """Direct unit tests for extract_strength_data."""

    def test_empty_metrics(self) -> None:
        result = extract_strength_data({})
        assert result.vibration_strength_db is None
        assert result.peak_amp_g is None
        assert result.noise_floor_amp_g is None
        assert result.strength_bucket is None
        assert strength_peak_payloads(result.top_peaks, max_items=8) == []

    def test_combined_strength_metrics(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 18.5,
                    "strength_bucket": "l3",
                    "peak_amp_g": 0.02,
                    "noise_floor_amp_g": 0.001,
                    "top_peaks": [{"hz": 45.0, "amp": 0.015}],
                },
            },
        }
        result = extract_strength_data(metrics)
        assert result.vibration_strength_db == pytest.approx(18.5)
        assert result.strength_bucket == "l3"
        payloads = strength_peak_payloads(result.top_peaks, max_items=8)
        assert len(payloads) == 1
        assert payloads[0]["hz"] == pytest.approx(45.0)

    def test_nested_combined_strength_metrics(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 12.0,
                    "strength_bucket": "l2",
                    "top_peaks": [],
                },
            },
        }
        result = extract_strength_data(metrics)
        assert result.vibration_strength_db == pytest.approx(12.0)
        assert result.strength_bucket == "l2"

    def test_invalid_peak_data_filtered(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 10.0,
                    "top_peaks": [
                        {"hz": float("nan"), "amp": 0.01},
                        {"hz": 50.0, "amp": float("inf")},
                        {"hz": -1.0, "amp": 0.01},
                        {"hz": 50.0, "amp": 0.01},
                        "not_a_dict",
                    ],
                },
            },
        }
        result = extract_strength_data(metrics)
        payloads = strength_peak_payloads(result.top_peaks, max_items=8)
        assert len(payloads) == 1
        assert payloads[0]["hz"] == pytest.approx(50.0)

    def test_empty_bucket_treated_as_none(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 5.0,
                    "strength_bucket": "",
                    "top_peaks": [],
                },
            },
        }
        result = extract_strength_data(metrics)
        assert result.strength_bucket is None

    def test_top_peaks_with_zero_amp_are_filtered(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "top_peaks": [
                        {"hz": 100.0, "amp": 0.0},
                        {"hz": 200.0, "amp": -1.0},
                        {"hz": 300.0, "amp": 0.5},
                    ],
                },
            },
        }
        result = extract_strength_data(metrics)
        payloads = strength_peak_payloads(result.top_peaks, max_items=8)
        assert len(payloads) == 1
        assert payloads[0]["hz"] == 300.0

    def test_invalid_scalar_fields_degrade_to_none(self) -> None:
        result = extract_strength_data(
            {
                "combined": {
                    "strength_metrics": {
                        "vibration_strength_db": "bad",
                        "peak_amp_g": float("nan"),
                        "noise_floor_amp_g": "invalid",
                        "top_peaks": [{"hz": 50.0, "amp": 0.2}],
                    },
                },
            },
        )
        assert result.vibration_strength_db is None
        assert result.peak_amp_g is None
        assert result.noise_floor_amp_g is None
        assert result.dominant_hz == 50.0
        assert strength_peak_payloads(result.top_peaks, max_items=8) == [{"hz": 50.0, "amp": 0.2}]

    def test_to_peak_payloads_respects_max_items(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "top_peaks": [{"hz": float(i), "amp": 0.01} for i in range(1, 12)],
                },
            },
        }
        result = extract_strength_data(metrics)
        assert len(result.top_peaks) == 11
        assert len(strength_peak_payloads(result.top_peaks, max_items=8)) == 8
