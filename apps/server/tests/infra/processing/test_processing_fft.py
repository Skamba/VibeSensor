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

    def test_nan_and_spike_block_stays_finite_without_mutating_input(self) -> None:
        block = np.array([[1.0, np.nan, 1.0, 9.0, 1.0]], dtype=np.float32)
        original = block.copy()

        result = medfilt3(block)

        np.testing.assert_allclose(result, np.array([[1.0, 1.0, 5.0, 1.0, 1.0]], dtype=np.float32))
        assert np.all(np.isfinite(result))
        assert np.isnan(block[0, 1])
        assert block[0, 3] == original[0, 3]

    def test_all_nan_block_is_sanitized_to_zero(self) -> None:
        block = np.full((3, 5), float("nan"), dtype=np.float32)
        result = medfilt3(block)
        assert np.all(np.isfinite(result))
        assert np.all(result == 0.0)


class TestNoiseFloor:
    """Tests for the P20 noise floor function."""

    def test_empty_array(self) -> None:
        assert noise_floor(np.array([], dtype=np.float32)) == 0.0

    def test_all_nan(self) -> None:
        assert noise_floor(np.array([float("nan"), float("nan")], dtype=np.float32)) == 0.0

    def test_positive_values(self) -> None:
        amps = np.array([0.01, 0.02, 0.03, 0.04, 0.05], dtype=np.float32)
        assert noise_floor(amps) == pytest.approx(0.018, abs=1e-6)


class TestFloatList:
    """Tests for array-to-list conversion."""

    def test_ndarray(self) -> None:
        arr = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        result = float_list(arr)
        assert isinstance(result, list)
        assert result == [1.0, 2.0, 3.0]
        assert all(type(value) is float for value in result)

    def test_ndarray_multidimensional_values_flatten_in_row_major_order(self) -> None:
        arr = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        result = float_list(arr)
        assert result == [1.0, 2.0, 3.0, 4.0]
        np.testing.assert_array_equal(arr, np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))

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
        """A pure sine at 50 Hz should dominate the combined spectrum."""
        sr = 512
        fft_n = 512
        t = np.arange(fft_n, dtype=np.float32) / sr
        signal = 0.1 * np.sin(2 * np.pi * 50 * t)
        block = np.stack([signal, signal, signal], axis=0)

        params = _make_fft_params(sr=sr, fft_n=fft_n, max_hz=200.0)
        result = compute_fft_spectrum(block, sr, **params)
        dominant_idx = int(np.argmax(result["combined_amp"]))
        top_peak = result["strength_metrics"]["top_peaks"][0]

        assert float(result["freq_slice"][dominant_idx]) == pytest.approx(50.0, abs=1.0)
        assert float(result["combined_amp"][dominant_idx]) > float(
            result["combined_amp"][dominant_idx - 1],
        )
        assert float(result["combined_amp"][dominant_idx]) > float(
            result["combined_amp"][dominant_idx + 1],
        )
        assert float(top_peak["hz"]) == pytest.approx(50.0, abs=1.0)
        assert float(top_peak["amp"]) > 0.0
        assert float(result["strength_metrics"]["vibration_strength_db"]) > 0.0
        for axis in ("x", "y", "z"):
            assert float(result["spectrum_by_axis"][axis]["amp"][dominant_idx]) == pytest.approx(
                float(result["combined_amp"][dominant_idx]),
            )
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

    def test_result_shapes_and_frequency_order_follow_analysis_slice(self) -> None:
        sr = 256
        fft_n = 256
        block = np.random.default_rng(42).standard_normal((3, fft_n)).astype(np.float32) * 0.01

        result = compute_fft_spectrum(block, sr, **_make_fft_params(sr=sr, fft_n=fft_n))
        freq_slice = result["freq_slice"]

        assert freq_slice.dtype == np.float32
        assert np.all(np.diff(freq_slice) >= 0.0)
        assert result["combined_amp"].dtype == np.float32
        assert result["combined_amp"].shape == freq_slice.shape
        assert np.isfinite(result["strength_metrics"]["vibration_strength_db"])
        assert isinstance(result["strength_metrics"]["top_peaks"], list)
        for axis in ("x", "y", "z"):
            axis_spectrum = result["spectrum_by_axis"][axis]
            assert axis_spectrum["freq"].dtype == np.float32
            np.testing.assert_array_equal(axis_spectrum["freq"], freq_slice)
            assert axis_spectrum["amp"].dtype == np.float32
            assert axis_spectrum["amp"].shape == freq_slice.shape
            assert isinstance(result["axis_peaks"][axis], list)

    def test_combined_spectrum_reports_multiple_axis_tones(self) -> None:
        sr = 512
        fft_n = 512
        t = np.arange(fft_n, dtype=np.float32) / sr
        block = np.stack(
            [
                0.1 * np.sin(2 * np.pi * 50 * t),
                0.05 * np.sin(2 * np.pi * 80 * t),
                np.zeros_like(t),
            ],
            axis=0,
        )

        result = compute_fft_spectrum(
            block,
            sr,
            **_make_fft_params(sr=sr, fft_n=fft_n, max_hz=200.0),
        )
        peak_freqs = [float(peak["hz"]) for peak in result["strength_metrics"]["top_peaks"][:2]]
        idx_50 = int(np.argmin(np.abs(result["freq_slice"] - 50.0)))
        idx_80 = int(np.argmin(np.abs(result["freq_slice"] - 80.0)))

        assert peak_freqs == pytest.approx([50.0, 80.0], abs=1.0)
        assert float(result["combined_amp"][idx_50]) > float(
            result["spectrum_by_axis"]["y"]["amp"][idx_50],
        )
        assert float(result["combined_amp"][idx_80]) > float(
            result["spectrum_by_axis"]["x"]["amp"][idx_80],
        )
        assert float(result["combined_amp"][idx_50]) < float(
            result["spectrum_by_axis"]["x"]["amp"][idx_50],
        )
        assert float(result["combined_amp"][idx_80]) < float(
            result["spectrum_by_axis"]["y"]["amp"][idx_80],
        )

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
