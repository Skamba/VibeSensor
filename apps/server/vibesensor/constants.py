"""Shared physical and analysis constants — single source of truth.

Every numeric literal that appears in more than one module should live here
so that a change only needs to happen in one place.
"""

from __future__ import annotations

from typing import Final

from vibesensor_core.vibration_strength import PEAK_BANDWIDTH_HZ as PEAK_BANDWIDTH_HZ
from vibesensor_core.vibration_strength import PEAK_SEPARATION_HZ as PEAK_SEPARATION_HZ

__all__ = [
    "CONFIDENCE_CEILING",
    "CONFIDENCE_FLOOR",
    "CONSTANT_SPEED_STDDEV_KMH",
    "FREQUENCY_EPSILON_HZ",
    "HARMONIC_2X",
    "KMH_TO_MPS",
    "LIGHT_STRENGTH_MAX_DB",
    "MEMS_NOISE_FLOOR_G",
    "MIN_ANALYSIS_FREQ_HZ",
    "MIN_OVERLAP_TOLERANCE",
    "MPS_TO_KMH",
    "MULTI_SENSOR_CORROBORATION_DB",
    "NEGLIGIBLE_STRENGTH_MAX_DB",
    "NUMERIC_TYPES",
    "ORDER_CONSTANT_SPEED_MIN_MATCH_RATE",
    "ORDER_MIN_CONFIDENCE",
    "ORDER_MIN_COVERAGE_POINTS",
    "ORDER_MIN_MATCH_POINTS",
    "ORDER_SUPPRESS_PERSISTENT_MIN_CONF",
    "ORDER_TOLERANCE_MIN_HZ",
    "ORDER_TOLERANCE_REL",
    "PEAK_BANDWIDTH_HZ",
    "PEAK_SEPARATION_HZ",
    "ROAD_RESONANCE_MAX_HZ",
    "ROAD_RESONANCE_MIN_HZ",
    "SECONDS_PER_MINUTE",
    "SILENCE_DB",
    "SNR_LOG_DIVISOR",
    "SPEED_BIN_WIDTH_KMH",
    "SPEED_COVERAGE_MIN_PCT",
    "SPEED_MIN_POINTS",
    "STEADY_SPEED_RANGE_KMH",
    "STEADY_SPEED_STDDEV_KMH",
    "WEAK_SPATIAL_DOMINANCE_THRESHOLD",
]

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
# Sensor / noise-floor
# ---------------------------------------------------------------------------
MEMS_NOISE_FLOOR_G: Final[float] = 0.001
"""Minimum realistic MEMS accelerometer noise floor (~0.001 g).

Used as the lower bound for SNR computations to prevent ratio blow-up
when the measured floor is near zero (sensor artifact / perfectly clean
signal)."""

# ---------------------------------------------------------------------------
# Road-surface resonance
# ---------------------------------------------------------------------------
ROAD_RESONANCE_MIN_HZ: Final[float] = 0.5
"""Lower bound of the road-surface resonance frequency range (Hz).

Covers body/suspension modes (~0.5–3 Hz); the primary low-frequency cutoff
is ``spectrum_min_hz`` in the processing config."""

ROAD_RESONANCE_MAX_HZ: Final[float] = 12.0
"""Upper bound of the road-surface resonance frequency range (Hz)."""

# ---------------------------------------------------------------------------
# Multi-sensor corroboration
# ---------------------------------------------------------------------------
MULTI_SENSOR_CORROBORATION_DB: Final[float] = 3.0
"""Bonus dB added when ≥2 sensors agree on a finding, boosting effective
confidence in the detected vibration."""

# ---------------------------------------------------------------------------
# Analysis frequency
# ---------------------------------------------------------------------------
MIN_ANALYSIS_FREQ_HZ: Final[float] = 5.0
"""Minimum frequency for analysis peaks.  Sub-road-resonance content
(body sway, suspension heave) is not actionable for drivetrain diagnostics
and dilutes findings.  Protects the report pipeline against old recorded
runs that lack the FFT-level ``spectrum_min_hz`` filter."""

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

# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------
CONFIDENCE_FLOOR: Final[float] = 0.08
"""Clamp lower bound for computed confidence so no finding is ever
completely dismissed."""

CONFIDENCE_CEILING: Final[float] = 0.97
"""Clamp upper bound for computed confidence so no finding is ever
shown as perfectly certain."""

SNR_LOG_DIVISOR: Final[float] = 2.5
"""Divisor for log1p(SNR) normalisation to [0, 1]."""

ORDER_SUPPRESS_PERSISTENT_MIN_CONF: Final[float] = 0.40
"""Minimum order-finding confidence to suppress a matching persistent-peak."""

# ---------------------------------------------------------------------------
# Strength-based classification thresholds
# ---------------------------------------------------------------------------
NEGLIGIBLE_STRENGTH_MAX_DB: Final[float] = 8.0
"""Upper bound (exclusive) of the negligible vibration band in dB.

Derived from the strength-labels table: the ``l1`` ("light") band starts
at this threshold, meaning values strictly below this are classified as
negligible."""

LIGHT_STRENGTH_MAX_DB: Final[float] = 16.0
"""Upper bound (exclusive) of the light vibration band in dB.

Derived from the strength-labels table: the ``l2`` ("moderate") band starts
at this threshold, meaning values below this are classified as light or
negligible."""

# ---------------------------------------------------------------------------
# Speed / phase classification
# ---------------------------------------------------------------------------
SPEED_BIN_WIDTH_KMH: Final[int] = 10
"""Width of each speed bin in km/h for speed-breakdown tables."""

SPEED_COVERAGE_MIN_PCT: Final[float] = 35.0
"""Minimum percentage of non-null speed samples required for speed-based
analysis to be considered valid."""

SPEED_MIN_POINTS: Final[int] = 8
"""Minimum number of speed data points required for speed-based analysis."""

STEADY_SPEED_STDDEV_KMH: Final[float] = 2.0
"""Standard deviation threshold (km/h) below which speed is considered steady."""

STEADY_SPEED_RANGE_KMH: Final[float] = 8.0
"""Range threshold (km/h) below which speed is considered steady."""

CONSTANT_SPEED_STDDEV_KMH: Final[float] = 0.5
"""Standard deviation threshold (km/h) below which speed is considered constant
(stricter than steady-speed)."""

# ---------------------------------------------------------------------------
# Rotational-order matching
# ---------------------------------------------------------------------------
ORDER_TOLERANCE_REL: Final[float] = 0.08
"""Relative frequency tolerance for matching observed peaks to predicted
rotational-order frequencies."""

ORDER_TOLERANCE_MIN_HZ: Final[float] = 0.5
"""Minimum absolute frequency tolerance (Hz) for order matching, preventing
overly tight matches at low frequencies."""

ORDER_MIN_MATCH_POINTS: Final[int] = 4
"""Minimum number of matched sample points for an order finding to be emitted."""

ORDER_MIN_COVERAGE_POINTS: Final[int] = 6
"""Minimum number of coverage points (samples with valid speed and peak data)
for an order finding to be considered."""

ORDER_MIN_CONFIDENCE: Final[float] = 0.25
"""Minimum confidence score for an order-tracking finding to be retained."""

ORDER_CONSTANT_SPEED_MIN_MATCH_RATE: Final[float] = 0.55
"""Minimum match rate for order findings under constant-speed conditions,
where higher consistency is expected."""

# ---------------------------------------------------------------------------
# Type-check helpers
# ---------------------------------------------------------------------------
NUMERIC_TYPES: Final[tuple[type, ...]] = (int, float)
"""Cached type-tuple for ``isinstance`` checks against numeric types.

Avoids creating a fresh ``(int, float)`` tuple on every call."""
