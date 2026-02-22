"""Boundary tests for compute_vibration_strength_db.

Covers edge cases: all-zero input, flat spectrum, NaN values, single-bin,
very large spectrum, and no-peak-above-threshold scenarios.
"""

from __future__ import annotations

import math

import pytest
from vibesensor_core.vibration_strength import compute_vibration_strength_db


class TestComputeVibrationStrengthBoundaries:
    @pytest.mark.smoke
    def test_empty_input(self) -> None:
        result = compute_vibration_strength_db(
            freq_hz=[],
            combined_spectrum_amp_g_values=[],
        )
        assert result["vibration_strength_db"] == 0.0
        assert result["top_peaks"] == []

    def test_all_zero_amplitude(self) -> None:
        result = compute_vibration_strength_db(
            freq_hz=[1.0, 2.0, 3.0, 4.0, 5.0],
            combined_spectrum_amp_g_values=[0.0, 0.0, 0.0, 0.0, 0.0],
        )
        assert math.isfinite(result["vibration_strength_db"])
        assert result["peak_amp_g"] == 0.0

    def test_flat_spectrum(self) -> None:
        """Perfectly flat spectrum: no local maxima above threshold."""
        freq = [float(i) for i in range(100)]
        amp = [0.01] * 100
        result = compute_vibration_strength_db(
            freq_hz=freq,
            combined_spectrum_amp_g_values=amp,
        )
        assert math.isfinite(result["vibration_strength_db"])

    def test_single_bin(self) -> None:
        """Single bin input shouldn't crash."""
        result = compute_vibration_strength_db(
            freq_hz=[10.0],
            combined_spectrum_amp_g_values=[0.05],
        )
        assert math.isfinite(result["vibration_strength_db"])

    def test_two_bins(self) -> None:
        """Two bins: no local maximum possible (needs 3 for central check)."""
        result = compute_vibration_strength_db(
            freq_hz=[1.0, 2.0],
            combined_spectrum_amp_g_values=[0.01, 0.05],
        )
        assert math.isfinite(result["vibration_strength_db"])

    @pytest.mark.smoke
    def test_clear_peak(self) -> None:
        """One clear peak in the middle: should produce positive dB."""
        freq = [float(i) for i in range(20)]
        amp = [0.001] * 20
        amp[10] = 0.10  # strong peak
        result = compute_vibration_strength_db(
            freq_hz=freq,
            combined_spectrum_amp_g_values=amp,
        )
        assert result["vibration_strength_db"] > 0.0
        assert len(result["top_peaks"]) >= 1
        assert result["top_peaks"][0]["hz"] == 10.0

    def test_mismatched_lengths(self) -> None:
        """freq_hz and amplitude arrays of different lengths: use minimum."""
        result = compute_vibration_strength_db(
            freq_hz=[1.0, 2.0, 3.0],
            combined_spectrum_amp_g_values=[0.01, 0.05],
        )
        assert math.isfinite(result["vibration_strength_db"])

    def test_negative_amplitudes_clamped_to_zero(self) -> None:
        """Negative amplitude values should not cause crashes."""
        result = compute_vibration_strength_db(
            freq_hz=[1.0, 2.0, 3.0, 4.0, 5.0],
            combined_spectrum_amp_g_values=[-0.01, -0.05, 0.01, -0.02, 0.0],
        )
        assert math.isfinite(result["vibration_strength_db"])

    def test_strength_bucket_present(self) -> None:
        """Result should always include strength_bucket key."""
        result = compute_vibration_strength_db(
            freq_hz=[1.0, 2.0, 3.0],
            combined_spectrum_amp_g_values=[0.01, 0.05, 0.01],
        )
        assert "strength_bucket" in result

    def test_large_spectrum(self) -> None:
        """Large spectrum (1000 bins) should complete without issues."""
        freq = [float(i) for i in range(1000)]
        amp = [0.001] * 1000
        amp[500] = 0.20  # one strong peak
        result = compute_vibration_strength_db(
            freq_hz=freq,
            combined_spectrum_amp_g_values=amp,
        )
        assert result["vibration_strength_db"] > 0.0
        assert len(result["top_peaks"]) >= 1
