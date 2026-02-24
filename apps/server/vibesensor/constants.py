"""Shared physical and analysis constants — single source of truth.

Every numeric literal that appears in more than one module should live here
so that a change only needs to happen in one place.
"""

from __future__ import annotations

from typing import Final

from vibesensor_core.vibration_strength import PEAK_BANDWIDTH_HZ as PEAK_BANDWIDTH_HZ
from vibesensor_core.vibration_strength import PEAK_SEPARATION_HZ as PEAK_SEPARATION_HZ

# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
MPS_TO_KMH: Final[float] = 3.6
"""Multiply metres-per-second by this to get kilometres-per-hour."""

KMH_TO_MPS: Final[float] = 1.0 / MPS_TO_KMH
"""Multiply kilometres-per-hour by this to get metres-per-second."""

# ---------------------------------------------------------------------------
# Strength floor
# ---------------------------------------------------------------------------
SILENCE_DB: Final[float] = -120.0
"""dB value representing silence / no meaningful vibration signal."""

# ---------------------------------------------------------------------------
# Spatial analysis
# ---------------------------------------------------------------------------
WEAK_SPATIAL_DOMINANCE_THRESHOLD: Final[float] = 1.2
"""Dominance ratio below which spatial separation between locations is
considered weak (i.e., the strongest location is less than 1.2x the
next-strongest, so the confidence in location attribution is low)."""

# ---------------------------------------------------------------------------
# Rotational-order analysis
# ---------------------------------------------------------------------------
SECONDS_PER_MINUTE: Final[float] = 60.0
"""Hz-to-RPM conversion factor (RPM = Hz × 60)."""

HARMONIC_2X: Final[float] = 2.0
"""Multiplier for the second harmonic of a fundamental frequency."""

MIN_OVERLAP_TOLERANCE: Final[float] = 0.025
"""Minimum relative tolerance used when checking whether two rotational
orders (e.g. driveshaft 1× and engine 1×) overlap in frequency."""

FREQUENCY_EPSILON_HZ: Final[float] = 1e-6
"""Tiny guard value to prevent division-by-zero in frequency ratios."""
