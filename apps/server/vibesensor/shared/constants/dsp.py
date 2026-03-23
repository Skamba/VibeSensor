"""DSP and spectrum-processing constants."""

from __future__ import annotations

from typing import Final

from vibesensor.vibration_strength import PEAK_BANDWIDTH_HZ as PEAK_BANDWIDTH_HZ
from vibesensor.vibration_strength import PEAK_SEPARATION_HZ as PEAK_SEPARATION_HZ

WAVEFORM_DISPLAY_HZ: Final[int] = 120
"""Decimated sample rate sent to the UI waveform chart (Hz)."""

FFT_UPDATE_HZ: Final[int] = 4
"""FFT recomputation rate (Hz)."""

FFT_N: Final[int] = 2048
"""FFT window size (samples, power of 2)."""

SPECTRUM_MIN_HZ: Final[float] = 5.0
"""Lower frequency bound for the spectrum display (Hz)."""

SPECTRUM_MAX_HZ: Final[float] = 200.0
"""Upper frequency bound for the spectrum display (Hz)."""
