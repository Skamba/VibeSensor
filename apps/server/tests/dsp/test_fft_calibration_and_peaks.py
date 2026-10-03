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
    result = computer.compute_fft_spectrum(block, _FS, spike_filter_enabled=False)
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


def test_peaks_must_clear_the_floor_threshold_and_be_separated() -> None:
    freq = np.arange(0.0, 100.0, 0.25)
    amp = np.full(freq.size, 0.01)
    amp[freq == 20.0] = 0.02  # 2x the floor: below the 2.6x threshold
    amp[freq == 60.0] = 0.05  # 5x the floor: a peak
    amp[freq == 60.5] = 0.04  # a second maximum 0.5 Hz away: inside the 1.2 Hz separation

    metrics = compute_vibration_strength_db(freq_hz=freq, combined_spectrum_amp_g_values=amp)

    assert [peak["hz"] for peak in metrics["top_peaks"]] == [60.0]
