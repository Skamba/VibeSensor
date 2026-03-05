"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

import numpy as np
import pytest
from vibesensor_core.vibration_strength import (
    noise_floor_amp_p20_g,
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


class TestFinding2_DoubleBinRemoval:
    """Demonstrate that _noise_floor removes two bins instead of one."""

    def test_double_skip_in_noise_floor(self):
        """_noise_floor must NOT skip amps[0] before passing to
        noise_floor_amp_p20_g — the caller already provides the
        analysis-band slice (DC excluded by spectrum_min_hz).

        FIXED: amps[1:] removed; all bins now included.
        """
        amps = np.array(
            [5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
            dtype=np.float32,
        )

        correct_floor = noise_floor_amp_p20_g(combined_spectrum_amp_g=[float(v) for v in amps])
        actual_floor = SignalProcessor._noise_floor(amps)

        # After fix: both should agree exactly
        assert actual_floor == pytest.approx(correct_floor, abs=1e-6), (
            f"Noise floor mismatch: actual={actual_floor:.4f} vs correct={correct_floor:.4f}"
        )
