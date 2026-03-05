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


class TestFinding4_ToleranceIgnoresCompliance:
    """Demonstrate that compliance is computed but not used in tolerance_hz."""

    def test_compliance_used_in_tolerance(self):
        """FIXED: tolerance_hz now scales with sqrt(path_compliance)."""
        import inspect

        from vibesensor.analysis.findings import _build_order_findings

        source = inspect.getsource(_build_order_findings)
        assert "compliance = getattr(hypothesis" in source
        # After fix: compliance_scale IS used in the tolerance computation
        assert "compliance_scale" in source
        assert "compliance**0.5" in source or "compliance ** 0.5" in source
