"""Spectrum smoothing and peak-selection regressions:
- _smooth_spectrum uses edge-padding instead of zero-padding to prevent
  boundary attenuation of edge frequency bins.
- _top_peaks (and compute_vibration_strength_db) considers the last
  spectrum bin as a potential peak candidate.
"""

from __future__ import annotations

from vibesensor_core.vibration_strength import compute_vibration_strength_db


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
        assert freq_hz[-1] in top_hz, f"Core: last-bin peak at {freq_hz[-1]} Hz not in {top_hz}"
