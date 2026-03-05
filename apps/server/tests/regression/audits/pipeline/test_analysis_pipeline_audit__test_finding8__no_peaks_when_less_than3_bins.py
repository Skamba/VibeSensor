"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

import pytest
from vibesensor_core.vibration_strength import (
    compute_vibration_strength_db,
)

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


class TestFinding8_NoPeaksWhenLessThan3Bins:
    """compute_vibration_strength_db cannot detect peaks with < 3 frequency bins."""

    @pytest.mark.parametrize("n_bins", [1, 2])
    def test_no_peaks_detected_for_small_spectra(self, n_bins: int):
        freq = [10.0 * (i + 1) for i in range(n_bins)]
        amps = [0.5] * n_bins  # Significant energy
        result = compute_vibration_strength_db(
            freq_hz=freq,
            combined_spectrum_amp_g_values=amps,
        )
        # Bug: returns 0 dB even though there is real energy
        assert result["vibration_strength_db"] == 0.0
        assert result["top_peaks"] == []
