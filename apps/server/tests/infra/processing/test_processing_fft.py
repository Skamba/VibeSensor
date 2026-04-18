"""Unit tests for vibesensor.infra.processing.fft pure spectral functions.

These tests validate the stateless FFT/spectral functions that were
extracted from the monolithic SignalProcessor class during the
processing package refactoring.  Because these functions are pure
(no shared state, no locks), they can be tested in isolation with
precise, deterministic inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.infra.processing.fft import (
    compute_fft_spectrum,
    float_list,
    medfilt3,
    noise_floor,
    smooth_spectrum,
)


def _make_fft_params(
    sr: int = 256,
    fft_n: int = 256,
    max_hz: float = 100.0,
) -> dict:
    """Build the common FFT parameter dict used by ``compute_fft_spectrum``."""
    window = np.hanning(fft_n).astype(np.float32)
    scale = float(2.0 / max(1.0, float(np.sum(window))))
    freqs = np.fft.rfftfreq(fft_n, d=1.0 / sr)
    valid = (freqs >= 0) & (freqs <= max_hz)
    return {
        "fft_window": window,
        "fft_scale": scale,
        "freq_slice": freqs[valid].astype(np.float32),
        "valid_idx": np.flatnonzero(valid),
    }


class TestMedfilt3:
    """Tests for the 3-point median spike filter."""

    def test_single_spike_removed(self) -> None:
        block = np.array([[0.0, 0.0, 10.0, 0.0, 0.0]], dtype=np.float32)
        result = medfilt3(block)
        # The spike at index 2 should be replaced by the median of [0, 10, 0] = 0
        assert result[0, 2] == pytest.approx(0.0)

    def test_edges_unchanged(self) -> None:
        block = np.array([[5.0, 0.0, 0.0, 0.0, 7.0]], dtype=np.float32)
        result = medfilt3(block)
        assert result[0, 0] == pytest.approx(5.0)
        assert result[0, -1] == pytest.approx(7.0)

    def test_short_block_unchanged(self) -> None:
        block = np.array([[1.0, 2.0]], dtype=np.float32)
        result = medfilt3(block)
        np.testing.assert_array_equal(result, block)

    def test_multi_axis(self) -> None:
        block = np.zeros((3, 5), dtype=np.float32)
        block[0, 2] = 100.0  # spike on x
        block[1, 3] = 200.0  # spike on y
        result = medfilt3(block)
        assert result[0, 2] == pytest.approx(0.0)
        assert result[1, 3] == pytest.approx(0.0)
        assert result[2, 2] == pytest.approx(0.0)

    def test_all_nan_block_is_sanitized_to_zero(self) -> None:
        block = np.full((3, 5), float("nan"), dtype=np.float32)
        result = medfilt3(block)
        assert np.all(np.isfinite(result))
        assert np.all(result == 0.0)


class TestSmoothSpectrum:
    """Tests for the sliding-average spectrum smoother."""

    def test_empty_array(self) -> None:
        result = smooth_spectrum(np.array([], dtype=np.float32))
        assert result.size == 0

    def test_identity_with_bins_1(self) -> None:
        amps = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        result = smooth_spectrum(amps, bins=1)
        np.testing.assert_allclose(result, amps)

    def test_output_same_length(self) -> None:
        amps = np.random.default_rng(42).random(100).astype(np.float32)
        result = smooth_spectrum(amps, bins=5)
        assert result.shape == amps.shape

    def test_smoothing_reduces_variance(self) -> None:
        amps = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0], dtype=np.float32)
        result = smooth_spectrum(amps, bins=3)
        assert np.var(result) < np.var(amps)

    def test_even_bins_rounded_up(self) -> None:
        """Even bin counts should be rounded up to the next odd number."""
        amps = np.ones(10, dtype=np.float32)
        result_4 = smooth_spectrum(amps, bins=4)
        result_5 = smooth_spectrum(amps, bins=5)
        np.testing.assert_allclose(result_4, result_5)

    def test_nan_input_is_sanitized_before_smoothing(self) -> None:
        amps = np.array([1.0, np.nan, 3.0], dtype=np.float32)
        result = smooth_spectrum(amps, bins=3)
        np.testing.assert_allclose(
            result,
            np.array([2.0 / 3.0, 4.0 / 3.0, 2.0], dtype=np.float32),
        )


class TestNoiseFloor:
    """Tests for the P20 noise floor function."""

    def test_empty_array(self) -> None:
        assert noise_floor(np.array([], dtype=np.float32)) == 0.0

    def test_all_nan(self) -> None:
        assert noise_floor(np.array([float("nan"), float("nan")], dtype=np.float32)) == 0.0

    def test_positive_values(self) -> None:
        amps = np.array([0.01, 0.02, 0.03, 0.04, 0.05], dtype=np.float32)
        floor = noise_floor(amps)
        assert floor > 0.0
        # Floor should be less than the max amplitude
        assert floor < float(amps.max())


class TestFloatList:
    """Tests for array-to-list conversion."""

    def test_ndarray(self) -> None:
        arr = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        result = float_list(arr)
        assert isinstance(result, list)
        assert result == [1.0, 2.0, 3.0]
        assert all(type(value) is float for value in result)

    def test_python_list(self) -> None:
        result = float_list([1, 2, 3])
        assert result == [1.0, 2.0, 3.0]

    def test_ndarray_non_finite_values_become_zero_without_mutating_input(self) -> None:
        arr = np.array([1.0, np.nan, np.inf, -np.inf], dtype=np.float32)
        result = float_list(arr)
        assert result == [1.0, 0.0, 0.0, 0.0]
        assert np.isnan(arr[1])
        assert np.isposinf(arr[2])
        assert np.isneginf(arr[3])


class TestComputeFftSpectrum:
    """Tests for the pure FFT spectrum computation."""

    def test_known_frequency(self) -> None:
        """A pure sine at 50 Hz should produce a peak near 50 Hz."""
        sr = 512
        fft_n = 512
        t = np.arange(fft_n, dtype=np.float32) / sr
        signal = 0.1 * np.sin(2 * np.pi * 50 * t)
        block = np.stack([signal, signal, signal], axis=0)

        params = _make_fft_params(sr=sr, fft_n=fft_n, max_hz=200.0)
        result = compute_fft_spectrum(block, sr, **params)

        assert "spectrum_by_axis" in result
        assert "combined_amp" in result
        assert "strength_metrics" in result
        assert "axis_peaks" in result

        for axis in ("x", "y", "z"):
            assert result["axis_peaks"][axis] == []

    def test_spike_filter_toggle(self) -> None:
        """Verify spike filter can be disabled."""
        sr = 256
        fft_n = 256
        block = np.random.default_rng(42).standard_normal((3, fft_n)).astype(np.float32) * 0.01
        block[0, 128] = 100.0  # spike

        params = _make_fft_params(sr=sr, fft_n=fft_n)
        with_filter = compute_fft_spectrum(
            block,
            sr,
            **params,
            spike_filter_enabled=True,
        )
        without_filter = compute_fft_spectrum(
            block,
            sr,
            **params,
            spike_filter_enabled=False,
        )

        # Without the filter, the spike should show larger combined amplitude
        max_with = float(np.max(with_filter["combined_amp"]))
        max_without = float(np.max(without_filter["combined_amp"]))
        assert max_without > max_with

    def test_preserves_first_analysis_bin_when_slice_starts_above_zero(self) -> None:
        sr = 512
        fft_n = 512
        t = np.arange(fft_n, dtype=np.float32) / sr
        signal = 0.5 * np.sin(2 * np.pi * 6 * t)
        block = np.stack([signal, signal, signal], axis=0)

        window = np.hanning(fft_n).astype(np.float32)
        scale = float(2.0 / max(1.0, float(np.sum(window))))
        freqs = np.fft.rfftfreq(fft_n, d=1.0 / sr)
        valid = (freqs >= 6.0) & (freqs <= 100.0)

        result = compute_fft_spectrum(
            block,
            sr,
            fft_window=window,
            fft_scale=scale,
            freq_slice=freqs[valid].astype(np.float32),
            valid_idx=np.flatnonzero(valid),
        )

        assert result["freq_slice"][0] == pytest.approx(6.0)
        assert float(result["spectrum_by_axis"]["x"]["amp"][0]) > 0.0
        assert float(result["combined_amp"][0]) > 0.0

    def test_returns_expected_keys(self) -> None:
        sr = 256
        fft_n = 256
        block = np.random.default_rng(42).standard_normal((3, fft_n)).astype(np.float32) * 0.01

        result = compute_fft_spectrum(block, sr, **_make_fft_params(sr=sr, fft_n=fft_n))

        expected_keys = {
            "freq_slice",
            "spectrum_by_axis",
            "combined_amp",
            "strength_metrics",
            "axis_peaks",
        }
        assert set(result.keys()) == expected_keys

    def test_zero_length_fft_block_returns_empty_result(self) -> None:
        result = compute_fft_spectrum(
            np.empty((3, 0), dtype=np.float32),
            256,
            fft_window=np.empty((0,), dtype=np.float32),
            fft_scale=1.0,
            freq_slice=np.empty((0,), dtype=np.float32),
            valid_idx=np.empty((0,), dtype=np.intp),
        )
        assert result["freq_slice"].size == 0
        assert result["combined_amp"].size == 0
        assert result["strength_metrics"]["vibration_strength_db"] == 0.0
        assert result["strength_metrics"]["top_peaks"] == []
        for axis in ("x", "y", "z"):
            assert result["spectrum_by_axis"][axis]["amp"].size == 0
            assert result["axis_peaks"][axis] == []
