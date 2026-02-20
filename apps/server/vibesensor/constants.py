"""Shared physical and analysis constants — single source of truth.

Every numeric literal that appears in more than one module should live here
so that a change only needs to happen in one place.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
MPS_TO_KMH: Final[float] = 3.6
"""Multiply metres-per-second by this to get kilometres-per-hour."""

KMH_TO_MPS: Final[float] = 1.0 / MPS_TO_KMH
"""Multiply kilometres-per-hour by this to get metres-per-second."""

# ---------------------------------------------------------------------------
# Spectrum / peak-finding defaults (re-exported from core for convenience)
# ---------------------------------------------------------------------------
from vibesensor_core import PEAK_BANDWIDTH_HZ as PEAK_BANDWIDTH_HZ  # noqa: E402, F811
from vibesensor_core import PEAK_SEPARATION_HZ as PEAK_SEPARATION_HZ  # noqa: E402, F811

# ---------------------------------------------------------------------------
# Strength floor
# ---------------------------------------------------------------------------
SILENCE_DB: Final[float] = -120.0
"""dB value representing silence / no meaningful vibration signal."""
