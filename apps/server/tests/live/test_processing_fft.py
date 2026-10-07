"""Unit tests for the shared FFTW-backed spectral analysis helpers.

These tests validate the stateless FFT/spectral functions that were
extracted from the monolithic SignalProcessor class during the
processing package refactoring.  Because these functions are pure
(no shared state, no locks), they can be tested in isolation with
precise, deterministic inputs.
"""

from __future__ import annotations

import numpy as np
import pyfftw
import pytest

import vibesensor.dsp.fft_analysis as fft_module
from vibesensor.dsp.fft_analysis import (
    SpectralAnalysisComputer,
    axis_peaks_from_spectrum,
    compute_fft_spectrum,
    float_list,
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
    freq_slice, valid_idx, _ = computer._fft_cache_entry(sr)
    return {
        "fft_window": computer.fft_window,
        "fft_scale": computer.fft_scale,
        "freq_slice": freq_slice,
        "valid_idx": valid_idx,
    }


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
            axis_peaks = axis_peaks_from_spectrum(
                freq_slice=result["freq_slice"], amp_slice=result["spectrum_by_axis"][axis]["amp"]
            )
            assert float(axis_peaks[0]["hz"]) == pytest.approx(50.0, abs=1.0)
            assert float(axis_peaks[0]["amp"]) > 0.0

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
        freq_slice, valid_idx, _ = computer._fft_cache_entry(sr)

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

    def test_strength_noise_floor_uses_first_analysis_bin_when_dc_is_absent(self) -> None:
        sr = 512
        fft_n = 512
        t = np.arange(fft_n, dtype=np.float32) / sr
        first_bin_tone = 0.05 * np.sin(2 * np.pi * 6 * t)
        upper_tone = 0.25 * np.sin(2 * np.pi * 10 * t)
        block = np.stack(
            [
                first_bin_tone + upper_tone,
                first_bin_tone + upper_tone,
                first_bin_tone + upper_tone,
            ],
            axis=0,
        )
        computer = SpectralAnalysisComputer(
            fft_n=fft_n,
            spectrum_min_hz=6.0,
            spectrum_max_hz=100.0,
        )
        freq_slice, valid_idx, _ = computer._fft_cache_entry(sr)

        result = compute_fft_spectrum(
            block,
            sr,
            fft_window=computer.fft_window,
            fft_scale=computer.fft_scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
        )

        assert result["freq_slice"][0] == pytest.approx(6.0)
        assert result["strength_metrics"]["top_peaks"]
        assert result["strength_metrics"]["top_peaks"][0]["hz"] == pytest.approx(10.0, abs=1.0)
        assert float(result["strength_metrics"]["noise_floor_amp_g"]) > 0.0

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
        monkeypatch.setattr(pyfftw, "empty_aligned", _fake_empty_aligned)
        monkeypatch.setattr(pyfftw, "FFTW", _fake_fftw)
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
            "has_valid_analysis_bins",
            "strength_metrics",
            "strength_metrics_analytically_valid",
        }
        assert freq_slice.dtype == np.float32
        assert result["combined_amp"].dtype == np.float32
        for axis in ("x", "y", "z"):
            axis_spectrum = result["spectrum_by_axis"][axis]
            assert axis_spectrum["freq"].dtype == np.float32
            np.testing.assert_array_equal(axis_spectrum["freq"], freq_slice)
            assert axis_spectrum["amp"].dtype == np.float32

        if expect_empty:
            assert freq_slice.size == 0
            assert result["combined_amp"].size == 0
            assert result["has_valid_analysis_bins"] is False
            assert result["strength_metrics_analytically_valid"] is False
            assert result["strength_metrics"]["vibration_strength_db"] == 0.0
            assert result["strength_metrics"]["top_peaks"] == []
            for axis in ("x", "y", "z"):
                assert result["spectrum_by_axis"][axis]["amp"].size == 0
            return

        assert np.all(np.diff(freq_slice) >= 0.0)
        assert result["combined_amp"].shape == freq_slice.shape
        assert result["has_valid_analysis_bins"] is True
        assert result["strength_metrics_analytically_valid"] is True
        assert np.isfinite(result["strength_metrics"]["vibration_strength_db"])
        assert isinstance(result["strength_metrics"]["top_peaks"], list)
        for axis in ("x", "y", "z"):
            assert result["spectrum_by_axis"][axis]["amp"].shape == freq_slice.shape

    def test_spectral_analysis_marks_no_valid_bin_slice_as_invalid(self) -> None:
        sample_rate_hz = 8
        fft_n = 64
        t = np.arange(fft_n, dtype=np.float32) / sample_rate_hz
        block = np.stack(
            [
                0.1 * np.sin(2 * np.pi * 2 * t),
                np.zeros_like(t),
                np.zeros_like(t),
            ],
            axis=0,
        )
        computer = SpectralAnalysisComputer(
            fft_n=fft_n,
            spectrum_min_hz=5.0,
            spectrum_max_hz=200.0,
        )

        result = computer.compute_fft_spectrum(block, sample_rate_hz)

        assert result["freq_slice"].size == 0
        assert result["has_valid_analysis_bins"] is False
        assert result["strength_metrics_analytically_valid"] is False
        assert result["strength_metrics"]["vibration_strength_db"] == 0.0
        assert result["strength_metrics"]["top_peaks"] == []

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
        x_axis_peak_freqs, y_axis_peak_freqs = (
            [
                float(peak["hz"])
                for peak in axis_peaks_from_spectrum(
                    freq_slice=result["freq_slice"],
                    amp_slice=result["spectrum_by_axis"][axis]["amp"],
                )[:1]
            ]
            for axis in ("x", "y")
        )
        idx_50 = int(np.argmin(np.abs(result["freq_slice"] - 50.0)))
        idx_80 = int(np.argmin(np.abs(result["freq_slice"] - 80.0)))

        assert peak_freqs == pytest.approx([50.0, 80.0], abs=1.0)
        assert x_axis_peak_freqs == pytest.approx([50.0], abs=1.0)
        assert y_axis_peak_freqs == pytest.approx([80.0], abs=1.0)
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
