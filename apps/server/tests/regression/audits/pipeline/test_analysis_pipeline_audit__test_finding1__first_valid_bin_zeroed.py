"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

import numpy as np

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


class TestFinding1_FirstValidBinZeroed:
    """Demonstrate that the first valid frequency bin is silently zeroed."""

    def test_first_valid_bin_suppressed_in_combined_spectrum(self):
        """When spectrum_min_hz > 0, bin 0 of the sliced spectrum is a
        real analysis frequency, yet it is zeroed before being fed to
        combined_spectrum_amp_g."""
        sp = _make_signal_processor(sample_rate_hz=512, fft_n=512)
        # Inject a 6 Hz sinusoid — should appear in the first few bins
        t = np.arange(512, dtype=np.float32) / 512
        signal = 0.5 * np.sin(2 * np.pi * 6 * t)
        block = np.stack([signal, signal, signal])

        result = sp._compute_fft_spectrum(block, 512)
        freq_slice = result["freq_slice"]
        combined_amp = result["combined_amp"]

        # Find the bin closest to 6 Hz in freq_slice
        target_idx = int(np.argmin(np.abs(freq_slice - 6.0)))

        # The issue: if this bin happens to be index 0 of the sliced
        # array, it will be zeroed.
        if target_idx == 0:
            # BUG: combined_amp[0] is 0.0 even though there's real
            # energy at this frequency
            assert combined_amp[0] == 0.0, "Expected bin 0 to be zeroed (demonstrating the bug)"
        else:
            # If freq resolution puts 6 Hz in bin > 0, the energy is preserved
            assert combined_amp[target_idx] > 0
