"""Unit tests for vibesensor.processing.fft pure spectral functions.

These tests validate the stateless FFT/spectral functions that were
extracted from the monolithic SignalProcessor class during the
processing package refactoring.  Because these functions are pure
(no shared state, no locks), they can be tested in isolation with
precise, deterministic inputs.
"""

from __future__ import annotations

import math

import numpy as np
import pytest


class TestMedfilt3:
    """Tests for the 3-point median spike filter."""

    def test_single_spike_removed(self) -> None:
        from vibesensor.processing.fft import medfilt3

        block = np.array([[0.0, 0.0, 10.0, 0.0, 0.0]], dtype=np.float32)
        result = medfilt3(block)
        # The spike at index 2 should be replaced by the median of [0, 10, 0] = 0
        assert result[0, 2] == pytest.approx(0.0)

    def test_edges_unchanged(self) -> None:
        from vibesensor.processing.fft import medfilt3

        block = np.array([[5.0, 0.0, 0.0, 0.0, 7.0]], dtype=np.float32)
        result = medfilt3(block)
        assert result[0, 0] == pytest.approx(5.0)
        assert result[0, -1] == pytest.approx(7.0)

    def test_short_block_unchanged(self) -> None:
        from vibesensor.processing.fft import medfilt3

        block = np.array([[1.0, 2.0]], dtype=np.float32)
        result = medfilt3(block)
        np.testing.assert_array_equal(result, block)

    def test_multi_axis(self) -> None:
        from vibesensor.processing.fft import medfilt3

        block = np.zeros((3, 5), dtype=np.float32)
        block[0, 2] = 100.0  # spike on x
        block[1, 3] = 200.0  # spike on y
        result = medfilt3(block)
        assert result[0, 2] == pytest.approx(0.0)
        assert result[1, 3] == pytest.approx(0.0)
        assert result[2, 2] == pytest.approx(0.0)


class TestSmoothSpectrum:
    """Tests for the sliding-average spectrum smoother."""

    def test_empty_array(self) -> None:
        from vibesensor.processing.fft import smooth_spectrum

        result = smooth_spectrum(np.array([], dtype=np.float32))
        assert result.size == 0

    def test_identity_with_bins_1(self) -> None:
        from vibesensor.processing.fft import smooth_spectrum

        amps = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        result = smooth_spectrum(amps, bins=1)
        np.testing.assert_allclose(result, amps)

    def test_output_same_length(self) -> None:
        from vibesensor.processing.fft import smooth_spectrum

        amps = np.random.rand(100).astype(np.float32)
        result = smooth_spectrum(amps, bins=5)
        assert result.shape == amps.shape

    def test_smoothing_reduces_variance(self) -> None:
        from vibesensor.processing.fft import smooth_spectrum

        amps = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0], dtype=np.float32)
        result = smooth_spectrum(amps, bins=3)
        assert np.var(result) < np.var(amps)

    def test_even_bins_rounded_up(self) -> None:
        """Even bin counts should be rounded up to the next odd number."""
        from vibesensor.processing.fft import smooth_spectrum

        amps = np.ones(10, dtype=np.float32)
        result_4 = smooth_spectrum(amps, bins=4)
        result_5 = smooth_spectrum(amps, bins=5)
        np.testing.assert_allclose(result_4, result_5)


class TestNoiseFloor:
    """Tests for the P20 noise floor function."""

    def test_empty_array(self) -> None:
        from vibesensor.processing.fft import noise_floor

        assert noise_floor(np.array([], dtype=np.float32)) == 0.0

    def test_all_nan(self) -> None:
        from vibesensor.processing.fft import noise_floor

        assert noise_floor(np.array([float("nan"), float("nan")], dtype=np.float32)) == 0.0

    def test_positive_values(self) -> None:
        from vibesensor.processing.fft import noise_floor

        amps = np.array([0.01, 0.02, 0.03, 0.04, 0.05], dtype=np.float32)
        floor = noise_floor(amps)
        assert floor > 0.0
        # Floor should be less than the max amplitude
        assert floor < float(amps.max())


class TestFloatList:
    """Tests for array-to-list conversion."""

    def test_ndarray(self) -> None:
        from vibesensor.processing.fft import float_list

        arr = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        result = float_list(arr)
        assert isinstance(result, list)
        assert result == [1.0, 2.0, 3.0]

    def test_python_list(self) -> None:
        from vibesensor.processing.fft import float_list

        result = float_list([1, 2, 3])
        assert result == [1.0, 2.0, 3.0]


class TestTopPeaks:
    """Tests for spectral peak detection."""

    def test_empty_input(self) -> None:
        from vibesensor.processing.fft import top_peaks

        result = top_peaks(np.array([]), np.array([]))
        assert result == []

    def test_single_peak(self) -> None:
        from vibesensor.processing.fft import top_peaks

        freqs = np.linspace(1, 100, 200, dtype=np.float32)
        amps = np.zeros(200, dtype=np.float32)
        amps[50] = 1.0  # Clear peak at index 50
        peaks = top_peaks(freqs, amps, top_n=3, smoothing_bins=1)
        assert len(peaks) >= 1
        assert peaks[0]["hz"] == pytest.approx(float(freqs[50]))

    def test_respects_top_n(self) -> None:
        from vibesensor.processing.fft import top_peaks

        freqs = np.linspace(1, 100, 200, dtype=np.float32)
        amps = np.zeros(200, dtype=np.float32)
        amps[30] = 0.8
        amps[60] = 0.6
        amps[90] = 0.4
        amps[120] = 0.2
        peaks = top_peaks(freqs, amps, top_n=2, smoothing_bins=1)
        assert len(peaks) <= 2


class TestComputeFftSpectrum:
    """Tests for the pure FFT spectrum computation."""

    def test_known_frequency(self) -> None:
        """A pure sine at 50 Hz should produce a peak near 50 Hz."""
        from vibesensor.processing.fft import compute_fft_spectrum

        sr = 512
        fft_n = 512
        t = np.arange(fft_n, dtype=np.float32) / sr
        signal = 0.1 * np.sin(2 * np.pi * 50 * t)
        block = np.stack([signal, signal, signal], axis=0)

        window = np.hanning(fft_n).astype(np.float32)
        scale = float(2.0 / max(1.0, float(np.sum(window))))
        freqs = np.fft.rfftfreq(fft_n, d=1.0 / sr)
        valid = (freqs >= 0) & (freqs <= 200)
        freq_slice = freqs[valid].astype(np.float32)
        valid_idx = np.flatnonzero(valid)

        result = compute_fft_spectrum(
            block,
            sr,
            fft_window=window,
            fft_scale=scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
        )

        assert "spectrum_by_axis" in result
        assert "combined_amp" in result
        assert "strength_metrics" in result
        assert "axis_peaks" in result

        # The dominant peak on each axis should be near 50 Hz
        for axis in ("x", "y", "z"):
            peaks = result["axis_peaks"][axis]
            assert len(peaks) >= 1
            assert abs(peaks[0]["hz"] - 50.0) < 2.0

    def test_spike_filter_toggle(self) -> None:
        """Verify spike filter can be disabled."""
        from vibesensor.processing.fft import compute_fft_spectrum

        sr = 256
        fft_n = 256
        block = np.random.randn(3, fft_n).astype(np.float32) * 0.01
        block[0, 128] = 100.0  # spike

        window = np.hanning(fft_n).astype(np.float32)
        scale = float(2.0 / max(1.0, float(np.sum(window))))
        freqs = np.fft.rfftfreq(fft_n, d=1.0 / sr)
        valid = (freqs >= 0) & (freqs <= 100)
        freq_slice = freqs[valid].astype(np.float32)
        valid_idx = np.flatnonzero(valid)

        with_filter = compute_fft_spectrum(
            block,
            sr,
            fft_window=window,
            fft_scale=scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
            spike_filter_enabled=True,
        )
        without_filter = compute_fft_spectrum(
            block,
            sr,
            fft_window=window,
            fft_scale=scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
            spike_filter_enabled=False,
        )

        # Without the filter, the spike should show larger combined amplitude
        max_with = float(np.max(with_filter["combined_amp"]))
        max_without = float(np.max(without_filter["combined_amp"]))
        assert max_without > max_with

    def test_returns_expected_keys(self) -> None:
        from vibesensor.processing.fft import compute_fft_spectrum

        sr = 256
        fft_n = 256
        block = np.random.randn(3, fft_n).astype(np.float32) * 0.01

        window = np.hanning(fft_n).astype(np.float32)
        scale = float(2.0 / max(1.0, float(np.sum(window))))
        freqs = np.fft.rfftfreq(fft_n, d=1.0 / sr)
        valid = (freqs >= 0) & (freqs <= 100)
        freq_slice = freqs[valid].astype(np.float32)
        valid_idx = np.flatnonzero(valid)

        result = compute_fft_spectrum(
            block,
            sr,
            fft_window=window,
            fft_scale=scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
        )

        expected_keys = {
            "freq_slice",
            "valid_idx",
            "spectrum_by_axis",
            "axis_amp_slices",
            "axis_amps",
            "combined_amp",
            "strength_metrics",
            "axis_peaks",
        }
        assert set(result.keys()) == expected_keys
