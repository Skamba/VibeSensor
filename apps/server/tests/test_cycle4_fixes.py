"""Tests for Cycle 4 fixes:
- _smooth_spectrum uses edge-padding instead of zero-padding to prevent
  boundary attenuation of edge frequency bins.
- _top_peaks (and compute_vibration_strength_db) considers the last
  spectrum bin as a potential peak candidate.
"""

from __future__ import annotations

import numpy as np
import pytest
from vibesensor_core.vibration_strength import compute_vibration_strength_db


class TestSmoothSpectrumEdgePadding:
    """Regression: _smooth_spectrum must not attenuate edge bins via
    zero-padding.  Using edge-replication prevents artificial reduction
    of boundary amplitudes."""

    def test_constant_signal_unchanged(self) -> None:
        """A constant-amplitude spectrum must be unchanged after smoothing."""
        from vibesensor.processing import SignalProcessor

        amps = np.full(20, 0.5, dtype=np.float32)
        smoothed = SignalProcessor._smooth_spectrum(amps, bins=5)
        np.testing.assert_allclose(smoothed, amps, atol=1e-6)

    def test_edge_not_attenuated(self) -> None:
        """First and last bins must not be reduced compared to the raw value
        when the signal is constant near the boundary."""
        from vibesensor.processing import SignalProcessor

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
        from vibesensor.processing import SignalProcessor

        amps = np.full(20, 0.1, dtype=np.float32)
        amps[-1] = 1.0
        amps[-2] = 0.8
        smoothed = SignalProcessor._smooth_spectrum(amps, bins=3)
        # With edge-padding the last bin should reflect the actual values,
        # not be dragged toward zero.
        assert smoothed[-1] > 0.85, (
            f"Last-bin smoothed value {smoothed[-1]} should remain high"
        )

    def test_output_length_matches_input(self) -> None:
        """Smoothed output must have the same length as the input."""
        from vibesensor.processing import SignalProcessor

        for n in (5, 10, 50, 200):
            amps = np.random.default_rng(42).random(n).astype(np.float32)
            smoothed = SignalProcessor._smooth_spectrum(amps, bins=5)
            assert smoothed.shape == amps.shape, f"Shape mismatch for n={n}"


class TestTopPeaksLastBin:
    """Regression: _top_peaks must consider the final spectrum bin as a
    valid peak candidate, not silently skip it."""

    def test_peak_at_last_bin_detected(self) -> None:
        """A clear peak at the last frequency bin must appear in results."""
        from vibesensor.processing import SignalProcessor

        n = 50
        freqs = np.arange(n, dtype=np.float32) * 4.0  # 0..196 Hz
        amps = np.full(n, 0.01, dtype=np.float32)
        # Place a strong peak at the last bin.
        amps[-1] = 1.0
        peaks = SignalProcessor._top_peaks(freqs, amps, top_n=5, smoothing_bins=1)
        peak_hz = [p["hz"] for p in peaks]
        assert float(freqs[-1]) in peak_hz, (
            f"Last-bin peak at {freqs[-1]} Hz not found in {peak_hz}"
        )

    def test_last_bin_not_detected_when_lower_than_neighbor(self) -> None:
        """Last bin should NOT be reported if it's lower than its neighbor."""
        from vibesensor.processing import SignalProcessor

        n = 50
        freqs = np.arange(n, dtype=np.float32) * 4.0
        amps = np.full(n, 0.01, dtype=np.float32)
        # Peak at second-to-last bin, last bin is lower.
        amps[-2] = 1.0
        amps[-1] = 0.5
        peaks = SignalProcessor._top_peaks(freqs, amps, top_n=5, smoothing_bins=1)
        peak_hz = [p["hz"] for p in peaks]
        assert float(freqs[-2]) in peak_hz, "Penultimate peak should be found"
        # Last bin is lower than its left neighbor and not a local max.
        assert float(freqs[-1]) not in peak_hz, "Last bin should not be a peak here"


class TestCoreStrengthLastBin:
    """Regression: compute_vibration_strength_db must consider the last
    spectrum bin as a peak candidate."""

    def test_peak_at_last_bin_detected_in_core(self) -> None:
        n = 50
        freq_hz = [float(i) * 4.0 for i in range(n)]
        combined = [0.001] * n
        combined[-1] = 1.0  # strong peak at last bin
        result = compute_vibration_strength_db(
            freq_hz=freq_hz,
            combined_spectrum_amp_g_values=combined,
            top_n=5,
        )
        top_hz = [p["hz"] for p in result["top_peaks"]]
        assert freq_hz[-1] in top_hz, (
            f"Core: last-bin peak at {freq_hz[-1]} Hz not in {top_hz}"
        )
