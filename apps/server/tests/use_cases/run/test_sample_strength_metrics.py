from __future__ import annotations

import pytest

from vibesensor.domain import StrengthMetrics
from vibesensor.shared.boundaries.codecs import (
    strength_metrics_from_mapping,
    strength_peak_payloads,
)
from vibesensor.shared.types.payload_types import ClientMetrics
from vibesensor.use_cases.run.sample_strength_metrics import (
    dominant_axis_from_metrics,
    dominant_hz_from_strength,
    extract_strength_data,
)


class TestExtractStrengthData:
    def test_empty_metrics_returns_empty_strength_metrics(self) -> None:
        assert extract_strength_data(ClientMetrics()) == StrengthMetrics()

    def test_combined_strength_metrics_round_trip(self) -> None:
        metrics: ClientMetrics = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 18.5,
                    "strength_bucket": "l3",
                    "peak_amp_g": 0.02,
                    "noise_floor_amp_g": 0.001,
                    "top_peaks": [
                        {
                            "hz": 45.0,
                            "amp": 0.015,
                            "vibration_strength_db": 18.5,
                            "strength_bucket": "l3",
                        }
                    ],
                },
            },
        }
        result = extract_strength_data(metrics)
        assert result.vibration_strength_db == pytest.approx(18.5)
        assert result.strength_bucket == "l3"
        assert strength_peak_payloads(result.top_peaks, max_items=8) == [
            {
                "hz": 45.0,
                "amp": 0.015,
                "vibration_strength_db": 18.5,
                "strength_bucket": "l3",
            }
        ]


class TestDominantHzFromStrength:
    def test_returns_first_peak_hz(self) -> None:
        sm = strength_metrics_from_mapping({"top_peaks": [{"hz": 42.0, "amp": 0.5}]})
        assert dominant_hz_from_strength(sm) == 42.0

    def test_empty(self) -> None:
        assert dominant_hz_from_strength(StrengthMetrics()) is None

    def test_invalid_first_peak_does_not_scan_ahead(self) -> None:
        sm = strength_metrics_from_mapping(
            {
                "top_peaks": [
                    {"hz": "bad", "amp": 0.5},
                    {"hz": 99.0, "amp": 0.4},
                ],
            },
        )
        assert dominant_hz_from_strength(sm) is None


class TestDominantAxisFromMetrics:
    def test_returns_empty_when_no_dominant_frequency(self) -> None:
        assert dominant_axis_from_metrics(ClientMetrics(), dominant_hz=None) == ""

    def test_returns_axis_when_peak_match_is_clear(self) -> None:
        metrics: ClientMetrics = {
            "x": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 42.0, "amp": 0.3}]},
            "y": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 42.0, "amp": 0.1}]},
            "z": {"rms": 0.0, "p2p": 0.0, "peaks": []},
        }
        assert dominant_axis_from_metrics(metrics, dominant_hz=42.0) == "x"

    def test_returns_combined_when_multiple_axes_match_without_clear_winner(self) -> None:
        metrics: ClientMetrics = {
            "x": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 42.0, "amp": 0.2}]},
            "y": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 42.0, "amp": 0.2}]},
            "z": {"rms": 0.0, "p2p": 0.0, "peaks": []},
        }
        assert dominant_axis_from_metrics(metrics, dominant_hz=42.0) == "combined"

    def test_returns_empty_when_dominant_peak_has_no_axis_evidence(self) -> None:
        metrics: ClientMetrics = {
            "x": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 20.0, "amp": 0.1}]},
            "y": {"rms": 0.0, "p2p": 0.0, "peaks": []},
            "z": {"rms": 0.0, "p2p": 0.0, "peaks": []},
        }
        assert dominant_axis_from_metrics(metrics, dominant_hz=42.0) == ""
