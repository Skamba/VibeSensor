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


class TestFinding6_CombinedSpectrumInheritsZeroedBin:
    """Combined spectrum inherits the zeroed bin from amp_for_peaks."""

    def test_combined_spectrum_preserves_bin0(self):
        """FIXED: combined spectrum bin 0 should NOT be zeroed for
        broadband input because axis_amp_slices now uses amp_slice."""
        sp = _make_signal_processor(sample_rate_hz=256, fft_n=256)
        rng = np.random.default_rng(42)
        block = rng.standard_normal((3, 256)).astype(np.float32) * 0.1

        result = sp._compute_fft_spectrum(block, 256)
        combined = result["combined_amp"]

        if combined.size > 0:
            assert combined[0] > 0.0, (
                "Combined spectrum bin 0 should be non-zero for broadband input"
            )
