"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

import pytest
from vibesensor_core.strength_bands import bucket_for_strength

from vibesensor.analysis.strength_labels import strength_label
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


class TestFinding3_BucketVsLabelInconsistency:
    """FIXED: bucket_for_strength now returns 'l0' for negative dB,
    consistent with strength_label returning 'negligible'."""

    @pytest.mark.parametrize("db_value", [-5.0, -0.1, -20.0])
    def test_negative_db_inconsistency(self, db_value: float):
        bucket = bucket_for_strength(db_value)
        label_key, label_text = strength_label(db_value, lang="en")
        # After fix: bucket returns 'l0', consistent with label 'negligible'
        assert bucket == "l0", f"bucket_for_strength({db_value}) should return 'l0'"
        assert label_key == "negligible", f"strength_label({db_value}) returns {label_key}"
