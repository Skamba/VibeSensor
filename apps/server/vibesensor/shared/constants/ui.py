"""UI update cadence constants."""

from __future__ import annotations

from typing import Final

UI_PUSH_HZ: Final[int] = 10
"""Frequency of lightweight metric pushes to the UI (Hz)."""

UI_HEAVY_PUSH_HZ: Final[int] = 4
"""Frequency of heavy (FFT spectrum) pushes to the UI (Hz)."""
