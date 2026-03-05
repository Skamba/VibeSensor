"""Spectrum smoothing and peak-selection regressions:
- _smooth_spectrum uses edge-padding instead of zero-padding to prevent
  boundary attenuation of edge frequency bins.
- _top_peaks (and compute_vibration_strength_db) considers the last
  spectrum bin as a potential peak candidate.
"""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.processing import SignalProcessor


class TestSmoothSpectrumEdgePadding:
    """Regression: _smooth_spectrum must not attenuate edge bins via
    zero-padding.  Using edge-replication prevents artificial reduction
    of boundary amplitudes."""

    def test_constant_signal_unchanged(self) -> None:
        """A constant-amplitude spectrum must be unchanged after smoothing."""
        amps = np.full(20, 0.5, dtype=np.float32)
        smoothed = SignalProcessor._smooth_spectrum(amps, bins=5)
        np.testing.assert_allclose(smoothed, amps, atol=1e-6)

    def test_edge_not_attenuated(self) -> None:
        """First and last bins must not be reduced compared to the raw value
        when the signal is constant near the boundary."""
        amps = np.full(20, 1.0, dtype=np.float32)
        smoothed = SignalProcessor._smooth_spectrum(amps, bins=5)
        # With zero-padding the first bin would be ~0.6; with edge-pad it stays 1.0.
        assert smoothed[0] == pytest.approx(1.0, abs=1e-6), (
            f"First bin {smoothed[0]} should not be attenuated"
        )
        assert smoothed[-1] == pytest.approx(1.0, abs=1e-6), (
            f"Last bin {smoothed[-1]} should not be attenuated"
        )

    def test_edge_peak_preserved(self) -> None:
        """A peak at the last bin must not be suppressed by zero-padding."""
        amps = np.full(20, 0.1, dtype=np.float32)
        amps[-1] = 1.0
        amps[-2] = 0.8
        smoothed = SignalProcessor._smooth_spectrum(amps, bins=3)
        # With edge-padding the last bin should reflect the actual values,
        # not be dragged toward zero.
        assert smoothed[-1] > 0.85, f"Last-bin smoothed value {smoothed[-1]} should remain high"

    def test_output_length_matches_input(self) -> None:
        """Smoothed output must have the same length as the input."""
        for n in (5, 10, 50, 200):
            amps = np.random.default_rng(42).random(n).astype(np.float32)
            smoothed = SignalProcessor._smooth_spectrum(amps, bins=5)
            assert smoothed.shape == amps.shape, f"Shape mismatch for n={n}"
