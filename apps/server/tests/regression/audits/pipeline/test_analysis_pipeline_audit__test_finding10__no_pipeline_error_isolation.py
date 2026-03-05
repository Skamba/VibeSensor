"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

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


class TestFinding10_NoPipelineErrorIsolation:
    """Demonstrate that a failure in one stage kills the entire summary."""

    def test_findings_failure_kills_entire_summary(self):
        from vibesensor.analysis.summary import summarize_run_data

        metadata: dict[str, Any] = {
            "run_id": "test-run",
            "raw_sample_rate_hz": 512,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "end_time_utc": "2025-01-01T00:01:00Z",
        }
        # Minimal valid samples
        samples = [
            {
                "t_s": float(i),
                "speed_kmh": 80.0,
                "accel_x_g": 0.01,
                "accel_y_g": 0.01,
                "accel_z_g": 1.0,
                "vibration_strength_db": 15.0,
                "strength_bucket": "l1",
                "top_peaks": [{"hz": 30.0, "amp": 0.05}],
            }
            for i in range(20)
        ]

        # Patch _build_findings to raise an exception
        with patch(
            "vibesensor.analysis.summary._build_findings",
            side_effect=RuntimeError("simulated findings failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated findings failure"):
                summarize_run_data(metadata, samples, lang="en", file_name="test")
