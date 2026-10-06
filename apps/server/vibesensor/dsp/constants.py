"""DSP and spectrum-processing constants."""

from __future__ import annotations

from typing import Final

from vibesensor.dsp.vibration_strength import PEAK_BANDWIDTH_HZ as _PEAK_BANDWIDTH_HZ
from vibesensor.dsp.vibration_strength import PEAK_SEPARATION_HZ as _PEAK_SEPARATION_HZ

PEAK_BANDWIDTH_HZ: Final[float] = _PEAK_BANDWIDTH_HZ
"""Bandwidth around each detected strength peak (Hz)."""

PEAK_SEPARATION_HZ: Final[float] = _PEAK_SEPARATION_HZ
"""Minimum separation between neighbouring detected peaks (Hz)."""

SAMPLE_RATE_HZ: Final[int] = 800
"""Expected live accelerometer sample rate per sensor (Hz)."""

WAVEFORM_BUFFER_SECONDS: Final[int] = 8
"""Per-client ring-buffer window length (seconds)."""

WAVEFORM_DISPLAY_HZ: Final[int] = 120
"""Decimated sample rate sent to the UI waveform chart (Hz)."""

FFT_UPDATE_HZ: Final[int] = 4
"""FFT recomputation rate (Hz)."""

FFT_N: Final[int] = 2048
"""FFT window size (samples, power of 2)."""

FFT_MIN_WINDOW_COVERAGE: Final[float] = 0.3
"""Least share of an FFT block's window energy its samples present must carry.

Frames lost on the way leave gaps in the block (``fill_lost_samples``). Down to
this share a tone's peak, timed at ``present_centre``, sits on its frequency as
closely as in an intact block; below it the peak scatters.
"""

SPECTRUM_MIN_HZ: Final[float] = 5.0
"""Lower frequency bound for the spectrum display (Hz)."""

SPECTRUM_MAX_HZ: Final[float] = 200.0
"""Upper frequency bound for the spectrum display (Hz)."""
