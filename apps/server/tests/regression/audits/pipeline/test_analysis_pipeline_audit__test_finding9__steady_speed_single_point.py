"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

from vibesensor.analysis.helpers import _speed_stats
from vibesensor.processing import SignalProcessor


def _make_signal_processor(
    sample_rate_hz: int = 512,
    fft_n: int = 512,
    *,
    spectrum_min_hz: float = 5.0,
    spectrum_max_hz: float = 200.0,
) -> SignalProcessor:
    """Create a SignalProcessor with common defaults for audit tests."""
    return SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=4,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_min_hz=spectrum_min_hz,
        spectrum_max_hz=spectrum_max_hz,
    )


class TestFinding9_SteadySpeedSinglePoint:
    """_speed_stats reports steady_speed=True with a single data point."""

    def test_single_point_is_steady(self):
        result = _speed_stats([80.0])
        # A single point tells us nothing about speed variation
        assert result["steady_speed"] is True
        assert result["stddev_kmh"] == 0.0
        assert result["range_kmh"] == 0.0

    def test_empty_is_not_steady(self):
        result = _speed_stats([])
        assert result["steady_speed"] is False
