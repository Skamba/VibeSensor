"""Unit tests for the shared FFTW-backed spectral analysis helpers.

These tests validate the stateless FFT/spectral functions that were
extracted from the monolithic SignalProcessor class during the
processing package refactoring.  Because these functions are pure
(no shared state, no locks), they can be tested in isolation with
precise, deterministic inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

import vibesensor.shared.fft_analysis as fft_module
from vibesensor.shared.fft_analysis import (
    SpectralAnalysisComputer,
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
    computer = SpectralAnalysisComputer(
        fft_n=fft_n,
        spectrum_min_hz=0.0,
        spectrum_max_hz=max_hz,
    )
    freq_slice, valid_idx = computer.fft_params(sr)
    return {
        "fft_window": computer.fft_window,
        "fft_scale": computer.fft_scale,
        "freq_slice": freq_slice,
        "valid_idx": valid_idx,
    }


class TestMedfilt3:
    """Tests for the 3-point median spike filter."""

    @pytest.mark.parametrize(
        ("build_block", "expected"),
        [
            pytest.param(
                lambda: np.array([[0.0, 0.0, 10.0, 0.0, 0.0]], dtype=np.float32),
                np.array([[0.0, 0.0, 0.0, 0.0, 0.0]], dtype=np.float32),
                id="single-spike",
            ),
            pytest.param(
                lambda: np.array([[5.0, 0.0, 0.0, 0.0, 7.0]], dtype=np.float32),
                np.array([[5.0, 0.0, 0.0, 0.0, 7.0]], dtype=np.float32),
                id="edges-unchanged",
            ),
            pytest.param(
                lambda: np.array([[1.0, 2.0]], dtype=np.float32),
                np.array([[1.0, 2.0]], dtype=np.float32),
                id="short-block",
            ),
            pytest.param(
                lambda: np.array(
                    [
                        [0.0, 0.0, 100.0, 0.0, 0.0],
                        [0.0, 0.0, 0.0, 200.0, 0.0],
                        [0.0, 0.0, 0.0, 0.0, 0.0],
                    ],
                    dtype=np.float32,
                ),
                np.zeros((3, 5), dtype=np.float32),
                id="multi-axis",
            ),
        ],
    )
    def test_medfilt3_behavior_cases(self, build_block, expected: np.ndarray) -> None:
        block = build_block()

        result = medfilt3(block)

        np.testing.assert_allclose(result, expected)

    @pytest.mark.parametrize(
        ("block", "expected"),
        [
            pytest.param(
                np.array([[1.0, np.nan, 1.0, 9.0, 1.0]], dtype=np.float32),
                np.array([[1.0, 1.0, 5.0, 1.0, 1.0]], dtype=np.float32),
                id="mixed-nan-and-spike",
            ),
            pytest.param(
                np.full((3, 5), float("nan"), dtype=np.float32),
                np.zeros((3, 5), dtype=np.float32),
                id="all-nan",
            ),
        ],
    )
    def test_medfilt3_nan_sanitization_cases(
        self,
        block: np.ndarray,
        expected: np.ndarray,
    ) -> None:
        original = block.copy()

        result = medfilt3(block)

        np.testing.assert_allclose(result, expected)
        assert np.all(np.isfinite(result))
        np.testing.assert_array_equal(
            np.nan_to_num(block, nan=-999.0, posinf=999.0, neginf=-999.0),
            np.nan_to_num(original, nan=-999.0, posinf=999.0, neginf=-999.0),
        )


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

    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            pytest.param(
                np.array([1.0, 2.0, 3.0], dtype=np.float32),
                [1.0, 2.0, 3.0],
                id="ndarray",
            ),
            pytest.param(
                np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
                [1.0, 2.0, 3.0, 4.0],
                id="multidimensional-ndarray",
            ),
            pytest.param([1, 2, 3], [1.0, 2.0, 3.0], id="python-list"),
            pytest.param(
                np.array([1.0, np.nan, np.inf, -np.inf], dtype=np.float32),
                [1.0, 0.0, 0.0, 0.0],
                id="non-finite-ndarray",
            ),
        ],
    )
    def test_float_list_cases(
        self,
        values: np.ndarray | list[int],
        expected: list[float],
    ) -> None:
        if isinstance(values, np.ndarray):
            original = values.copy()
        else:
            original = list(values)

        result = float_list(values)

        assert isinstance(result, list)
        assert result == expected
        assert all(type(value) is float for value in result)
        if isinstance(values, np.ndarray):
            np.testing.assert_array_equal(
                np.nan_to_num(values, nan=-999.0, posinf=999.0, neginf=-999.0),
                np.nan_to_num(original, nan=-999.0, posinf=999.0, neginf=-999.0),
            )
        else:
            assert values == original


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
        computer = SpectralAnalysisComputer(
            fft_n=fft_n,
            spectrum_min_hz=6.0,
            spectrum_max_hz=100.0,
        )
        freq_slice, valid_idx = computer.fft_params(sr)

        result = compute_fft_spectrum(
            block,
            sr,
            fft_window=computer.fft_window,
            fft_scale=computer.fft_scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
        )

        assert result["freq_slice"][0] == pytest.approx(6.0)
        assert float(result["spectrum_by_axis"]["x"]["amp"][0]) > 0.0
        assert float(result["combined_amp"][0]) > 0.0

    def test_dc_bias_does_not_mask_signal_peak(self) -> None:
        sr = 512
        fft_n = 512
        t = np.arange(fft_n, dtype=np.float32) / sr
        block = np.stack(
            [
                np.full_like(t, 5.0) + 0.2 * np.sin(2 * np.pi * 40 * t),
                np.full_like(t, -3.0),
                np.full_like(t, 1.5),
            ],
            axis=0,
        )

        result = compute_fft_spectrum(
            block,
            sr,
            **_make_fft_params(sr=sr, fft_n=fft_n, max_hz=200.0),
        )

        assert float(result["strength_metrics"]["top_peaks"][0]["hz"]) == pytest.approx(
            40.0,
            abs=1.0,
        )

    def test_high_frequency_edge_tone_stays_visible(self) -> None:
        sr = 512
        fft_n = 512
        t = np.arange(fft_n, dtype=np.float32) / sr
        edge_tone = 0.15 * np.sin(2 * np.pi * 255 * t)
        block = np.stack([edge_tone, edge_tone, edge_tone], axis=0)

        result = compute_fft_spectrum(
            block,
            sr,
            **_make_fft_params(sr=sr, fft_n=fft_n, max_hz=256.0),
        )

        assert float(result["strength_metrics"]["top_peaks"][0]["hz"]) == pytest.approx(
            255.0,
            abs=1.0,
        )

    def test_get_rfft_plan_uses_estimate_planning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        original_cache = fft_module._PLAN_CACHE.copy()

        class FakePlan:
            def __init__(self, input_array: np.ndarray, output_array: np.ndarray) -> None:
                self.input_array = input_array
                self.output_array = output_array

            def __call__(self) -> np.ndarray:
                return self.output_array

        def _fake_empty_aligned(
            shape: tuple[int, ...],
            *,
            dtype: np.dtype[np.generic],
        ) -> np.ndarray:
            return np.empty(shape, dtype=dtype)

        def _fake_fftw(
            input_array: np.ndarray,
            output_array: np.ndarray,
            *,
            axes: tuple[int, ...],
            direction: str,
            flags: tuple[str, ...],
            threads: int,
        ) -> FakePlan:
            captured["axes"] = axes
            captured["direction"] = direction
            captured["flags"] = flags
            captured["threads"] = threads
            return FakePlan(input_array, output_array)

        fft_module._PLAN_CACHE.clear()
        monkeypatch.setattr(fft_module.pyfftw, "empty_aligned", _fake_empty_aligned)
        monkeypatch.setattr(fft_module.pyfftw, "FFTW", _fake_fftw)
        try:
            plan = fft_module._get_rfft_plan(3, 256)
        finally:
            fft_module._PLAN_CACHE.clear()
            fft_module._PLAN_CACHE.update(original_cache)

        assert isinstance(plan, FakePlan)
        assert captured == {
            "axes": (1,),
            "direction": "FFTW_FORWARD",
            "flags": ("FFTW_ESTIMATE",),
            "threads": 1,
        }

    @pytest.mark.parametrize(
        ("block", "sample_rate_hz", "params", "expect_empty"),
        [
            pytest.param(
                np.random.default_rng(42).standard_normal((3, 256)).astype(np.float32) * 0.01,
                256,
                _make_fft_params(sr=256, fft_n=256),
                False,
                id="populated-spectrum",
            ),
            pytest.param(
                np.empty((3, 0), dtype=np.float32),
                256,
                {
                    "fft_window": np.empty((0,), dtype=np.float32),
                    "fft_scale": 1.0,
                    "freq_slice": np.empty((0,), dtype=np.float32),
                    "valid_idx": np.empty((0,), dtype=np.intp),
                },
                True,
                id="empty-spectrum",
            ),
        ],
    )
    def test_compute_fft_spectrum_output_contract(
        self,
        block: np.ndarray,
        sample_rate_hz: int,
        params: dict[str, object],
        expect_empty: bool,
    ) -> None:
        result = compute_fft_spectrum(block, sample_rate_hz, **params)
        freq_slice = result["freq_slice"]

        assert set(result) == {
            "freq_slice",
            "spectrum_by_axis",
            "combined_amp",
            "strength_metrics",
            "axis_peaks",
        }
        assert freq_slice.dtype == np.float32
        assert result["combined_amp"].dtype == np.float32
        for axis in ("x", "y", "z"):
            axis_spectrum = result["spectrum_by_axis"][axis]
            assert axis_spectrum["freq"].dtype == np.float32
            np.testing.assert_array_equal(axis_spectrum["freq"], freq_slice)
            assert axis_spectrum["amp"].dtype == np.float32
            assert isinstance(result["axis_peaks"][axis], list)

        if expect_empty:
            assert freq_slice.size == 0
            assert result["combined_amp"].size == 0
            assert result["strength_metrics"]["vibration_strength_db"] == 0.0
            assert result["strength_metrics"]["top_peaks"] == []
            for axis in ("x", "y", "z"):
                assert result["spectrum_by_axis"][axis]["amp"].size == 0
                assert result["axis_peaks"][axis] == []
            return

        assert np.all(np.diff(freq_slice) >= 0.0)
        assert result["combined_amp"].shape == freq_slice.shape
        assert np.isfinite(result["strength_metrics"]["vibration_strength_db"])
        assert isinstance(result["strength_metrics"]["top_peaks"], list)
        for axis in ("x", "y", "z"):
            assert result["spectrum_by_axis"][axis]["amp"].shape == freq_slice.shape

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
