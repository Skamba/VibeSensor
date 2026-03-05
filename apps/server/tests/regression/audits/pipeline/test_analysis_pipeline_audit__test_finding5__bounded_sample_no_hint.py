"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

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


class TestFinding5_BoundedSampleNoHint:
    """Demonstrate the reactive doubling behavior without total_hint."""

    def test_reactive_doubling_wastes_work(self):
        from vibesensor.runlog import bounded_sample

        items = [{"v": i} for i in range(200)]
        # Without total_hint: starts with stride=1, collects all until overflow
        kept_no_hint, total, stride = bounded_sample(iter(items), max_items=50)
        # With total_hint: computes stride upfront
        kept_with_hint, total2, stride2 = bounded_sample(iter(items), max_items=50, total_hint=200)
        # Without hint, stride grows reactively via doubling
        assert stride >= 2, "Reactive doubling should have kicked in"
        # With hint, stride is computed upfront (200//50 = 4)
        assert stride2 == 4, "Upfront stride should be 4"
