"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

from vibesensor.analysis.phase_segmentation import (
    segment_run_phases,
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


class TestFinding7_PhaseSegmentIndexAsSeconds:
    """Phase segmentation uses NaN sentinel when time is missing."""

    def test_missing_time_uses_nan_sentinel(self):
        # Samples with no t_s → time falls back to NaN sentinel
        samples = [
            {"speed_kmh": 80.0}  # no t_s
            for _ in range(20)
        ]
        per_sample_phases, segments = segment_run_phases(samples)
        assert len(segments) > 0
        seg = segments[0]
        # Fixed: start_t_s and end_t_s are NaN (unknown), not sample indices
        import math

        assert math.isnan(seg.start_t_s)
        assert math.isnan(seg.end_t_s)
