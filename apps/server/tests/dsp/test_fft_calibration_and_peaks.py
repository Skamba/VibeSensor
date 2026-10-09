"""FFT amplitude calibration, window leakage and peak picking on known signals."""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer
from vibesensor.dsp.vibration_strength import compute_vibration_strength_db

_FS = 800
_N = 2048


def _x_axis_spectrum(bin_index: float, amplitude_g: float) -> tuple[np.ndarray, np.ndarray]:
    freq_hz = bin_index * _FS / _N
    t = np.arange(_N) / _FS
    block = np.zeros((3, _N), dtype=np.float32)
    block[0] = amplitude_g * np.sin(2 * np.pi * freq_hz * t)
    computer = SpectralAnalysisComputer(fft_n=_N, spectrum_min_hz=5.0, spectrum_max_hz=200.0)
    result = computer.compute_fft_spectrum(block, _FS)
    axis = result["spectrum_by_axis"]["x"]
    return np.asarray(axis["freq"]), np.asarray(axis["amp"])


def test_a_bin_centred_sine_reads_its_peak_amplitude_in_g() -> None:
    freq, amp = _x_axis_spectrum(100, 0.1)

    peak = int(np.argmax(amp))
    assert freq[peak] == pytest.approx(100 * _FS / _N)
    assert amp[peak] == pytest.approx(0.1, rel=0.01)


def test_the_hann_window_keeps_off_bin_leakage_local() -> None:
    _freq, amp = _x_axis_spectrum(100.5, 0.1)

    peak = int(np.argmax(amp))
    # A rectangular window would leak ~5% of the peak ten bins away.
    assert amp[peak + 10] < 0.01 * amp[peak]


@pytest.mark.parametrize("bin_index", [33.0, 33.25, 33.5, 33.8])
def test_a_peak_reads_its_tone_frequency_between_bins(bin_index: float) -> None:
    # About 13 Hz, a wheel order at motorway speed, where one bin is 3 %.
    computer = SpectralAnalysisComputer(fft_n=_N, spectrum_min_hz=5.0, spectrum_max_hz=200.0)
    t = np.arange(_N) / _FS
    block = np.random.default_rng(3).normal(0.0, 0.002, size=(3, _N)).astype(np.float32)
    block[2] += np.float32(0.05) * np.sin(2 * np.pi * bin_index * _FS / _N * t)

    top = computer.compute_fft_spectrum(block, _FS)["strength_metrics"]["top_peaks"][0]

    assert top["hz"] == pytest.approx(bin_index * _FS / _N, abs=0.05 * _FS / _N)


def test_peaks_must_clear_the_floor_threshold_and_be_separated() -> None:
    freq = np.arange(0.0, 100.0, 0.25)
    amp = np.full(freq.size, 0.01)
    amp[freq == 20.0] = 0.02  # 2x the floor: below the 2.6x threshold
    amp[freq == 60.0] = 0.05  # 5x the floor: a peak
    amp[freq == 60.5] = 0.04  # a second maximum 0.5 Hz away: inside the 1.2 Hz separation

    metrics = compute_vibration_strength_db(freq_hz=freq, combined_spectrum_amp_g_values=amp)

    assert [peak["hz"] for peak in metrics["top_peaks"]] == [60.0]


def test_the_combined_strength_alone_matches_the_full_spectrum() -> None:
    # Post-stop replay needs only the combined strength and spectrum; they must
    # be the full (live) spectrum's, value for value.
    rng = np.random.default_rng(11)
    computer = SpectralAnalysisComputer(fft_n=_N, spectrum_min_hz=5.0, spectrum_max_hz=200.0)
    t = np.arange(_N) / _FS
    for _ in range(5):
        block = rng.normal(0.0, 0.01, size=(3, _N)).astype(np.float32)
        block[rng.integers(3)] += np.float32(0.2) * np.sin(2 * np.pi * rng.uniform(5, 150) * t)

        full = computer.compute_fft_spectrum(block, _FS)
        combined = computer.compute_combined_strength_metrics(block, _FS)

        assert full["has_valid_analysis_bins"]
        assert combined is not None
        metrics, spectrum = combined
        assert metrics == full["strength_metrics"]
        np.testing.assert_array_equal(spectrum.freq_hz, full["freq_slice"])
        np.testing.assert_array_equal(spectrum.amp_g, full["combined_amp"])


def test_no_combined_strength_without_analysis_bins() -> None:
    computer = SpectralAnalysisComputer(fft_n=_N, spectrum_min_hz=500.0, spectrum_max_hz=600.0)

    block = np.zeros((3, _N), dtype=np.float32)

    assert not computer.compute_fft_spectrum(block, _FS)["has_valid_analysis_bins"]
    assert computer.compute_combined_strength_metrics(block, _FS) is None


def test_peak_picking_and_hann_window_match_scipy_signal() -> None:
    # The live path uses numpy versions so the server need not import
    # scipy.signal at start; they must stay identical to scipy's.
    from scipy.signal import find_peaks, windows

    from vibesensor.dsp.fft_analysis import fft_window_values
    from vibesensor.dsp.vibration_strength import _local_maxima

    rng = np.random.default_rng(7)
    for trial in range(2000):
        n = int(rng.integers(0, 40))
        # Few distinct levels give plateaus at the edges and in the middle.
        values = rng.integers(0, 4, size=n).astype(np.float64)
        if trial % 2:
            values = rng.normal(size=n)
        if trial % 5 == 0 and n:
            values[rng.integers(0, n)] = np.nan
        np.testing.assert_array_equal(_local_maxima(values), find_peaks(values)[0])
    for fft_n in (1, 2, 3, 512, 2048):
        expected = np.asarray(windows.hann(fft_n, sym=True), dtype=np.float32)
        np.testing.assert_array_equal(fft_window_values(fft_n=fft_n), expected)
