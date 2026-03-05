"""Spectrum smoothing and peak-selection regressions:
- _smooth_spectrum uses edge-padding instead of zero-padding to prevent
  boundary attenuation of edge frequency bins.
- _top_peaks (and compute_vibration_strength_db) considers the last
  spectrum bin as a potential peak candidate.
"""

from __future__ import annotations

import numpy as np

from vibesensor.processing import SignalProcessor


class TestTopPeaksLastBin:
    """Regression: _top_peaks must consider the final spectrum bin as a
    valid peak candidate, not silently skip it."""

    def test_peak_at_last_bin_detected(self) -> None:
        """A clear peak at the last frequency bin must appear in results."""
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
