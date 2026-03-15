# ruff: noqa: E402
from __future__ import annotations

"""Analysis pipeline audit – correctness and determinism regressions."""


from typing import Any

import numpy as np
import pytest

from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.processing.fft import noise_floor
from vibesensor.strength_bands import bucket_for_strength
from vibesensor.use_cases.diagnostics.helpers import _speed_stats
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    segment_run_phases,
)
from vibesensor.use_cases.diagnostics.strength_labels import strength_label
from vibesensor.vibration_strength import (
    compute_vibration_strength_db,
    noise_floor_amp_p20_g,
)


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


class TestFirstValidBinZeroed:
    """Demonstrate that the first valid frequency bin is silently zeroed."""

    def test_first_valid_bin_suppressed_in_combined_spectrum(self):
        """When spectrum_min_hz > 0, bin 0 of the sliced spectrum is a
        real analysis frequency, yet it is zeroed before being fed to
        combined_spectrum_amp_g.
        """
        sp = _make_signal_processor(sample_rate_hz=512, fft_n=512)
        # Inject a 6 Hz sinusoid — should appear in the first few bins
        t = np.arange(512, dtype=np.float32) / 512
        signal = 0.5 * np.sin(2 * np.pi * 6 * t)
        block = np.stack([signal, signal, signal])

        result = sp._metrics.compute_fft_spectrum(block, 512)
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


class TestDoubleBinRemoval:
    """Demonstrate that _noise_floor removes two bins instead of one."""

    def test_double_skip_in_noise_floor(self):
        """_noise_floor must NOT skip amps[0] before passing to
        noise_floor_amp_p20_g — the caller already provides the
        analysis-band slice (DC excluded by spectrum_min_hz).
        """
        amps = np.array(
            [5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
            dtype=np.float32,
        )

        correct_floor = noise_floor_amp_p20_g(combined_spectrum_amp_g=[float(v) for v in amps])
        actual_floor = noise_floor(amps)

        # After fix: both should agree exactly
        assert actual_floor == pytest.approx(correct_floor, abs=1e-6), (
            f"Noise floor mismatch: actual={actual_floor:.4f} vs correct={correct_floor:.4f}"
        )


class TestBucketVsLabelInconsistency:
    """
    consistent with strength_label returning 'negligible'.
    """

    @pytest.mark.parametrize("db_value", [-5.0, -0.1, -20.0])
    def test_negative_db_inconsistency(self, db_value: float):
        bucket = bucket_for_strength(db_value)
        label_key, label_text = strength_label(db_value, lang="en")
        # After fix: bucket returns 'l0', consistent with label 'negligible'
        assert bucket == "l0", f"bucket_for_strength({db_value}) should return 'l0'"
        assert label_key == "negligible", f"strength_label({db_value}) returns {label_key}"


class TestBoundedSampleNoHint:
    """Demonstrate the reactive doubling behavior without total_hint."""

    def test_reactive_doubling_wastes_work(self):
        from vibesensor.adapters.persistence.runlog import bounded_sample

        items = [{"v": i} for i in range(200)]
        # Without total_hint: starts with stride=1, collects all until overflow
        kept_no_hint, total, stride = bounded_sample(iter(items), max_items=50)
        # With total_hint: computes stride upfront
        kept_with_hint, total2, stride2 = bounded_sample(iter(items), max_items=50, total_hint=200)
        # Without hint, stride grows reactively via doubling
        assert stride >= 2, "Reactive doubling should have kicked in"
        # With hint, stride is computed upfront (200//50 = 4)
        assert stride2 == 4, "Upfront stride should be 4"


class TestCombinedSpectrumInheritsZeroedBin:
    """Combined spectrum inherits the zeroed bin from amp_for_peaks."""

    def test_combined_spectrum_preserves_bin0(self):
        """Combined spectrum preserves bin 0 because spectrum_by_axis
        stores the original amp_slice, not the DC-zeroed amp_for_peaks.
        """
        sp = _make_signal_processor(sample_rate_hz=256, fft_n=256)
        rng = np.random.default_rng(42)
        block = rng.standard_normal((3, 256)).astype(np.float32) * 0.1

        result = sp._metrics.compute_fft_spectrum(block, 256)
        combined = result["combined_amp"]

        if combined.size > 0:
            assert combined[0] > 0.0, (
                "Combined spectrum bin 0 should be non-zero for broadband input"
            )


class TestPhaseSegmentIndexAsSeconds:
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


class TestNoPeaksWhenLessThan3Bins:
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
        # Should have found the 0.5g amplitude as a peak


class TestSteadySpeedSinglePoint:
    """_speed_stats reports steady_speed=True with a single data point."""

    def test_single_point_is_steady(self):
        result = _speed_stats([80.0])
        # A single point tells us nothing about speed variation
        assert result["steady_speed"] is True
        assert result["stddev_kmh"] == 0.0
        assert result["range_kmh"] == 0.0

    def test_empty_is_not_steady(self):
        result = _speed_stats([])
        assert result["steady_speed"] is False


class TestNoPipelineErrorIsolation:
    """Demonstrate that a failure in one stage kills the entire summary."""

    def test_findings_failure_kills_entire_summary(self):
        from vibesensor.use_cases.diagnostics import summarize_run_data

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

        def _failing_findings_builder(**_kwargs: object) -> tuple:  # type: ignore[type-arg]
            raise RuntimeError("simulated findings failure")

        with pytest.raises(RuntimeError, match="simulated findings failure"):
            summarize_run_data(
                metadata,
                samples,
                lang="en",
                file_name="test",
                findings_builder=_failing_findings_builder,
            )
        # Bug: the entire summary is lost; no partial results are available
