"""Analysis and scoring constants shared by diagnostics and reporting."""

from __future__ import annotations

from typing import Final

SILENCE_DB: Final[float] = -120.0
"""dB value representing silence / no meaningful vibration signal."""

MEMS_NOISE_FLOOR_G: Final[float] = 0.001
"""Minimum realistic MEMS accelerometer noise floor (~0.001 g).

Used as the lower bound for SNR computations to prevent ratio blow-up when
the measured floor is near zero (sensor artifact / perfectly clean signal).
"""

MULTI_SENSOR_CORROBORATION_DB: Final[float] = 3.0
"""Bonus dB added when ≥2 sensors agree on a finding, boosting effective
confidence in the detected vibration."""

MIN_ANALYSIS_FREQ_HZ: Final[float] = 5.0
"""Minimum frequency for analysis peaks.

Sub-road-resonance content (body sway, suspension heave) is not actionable
for drivetrain diagnostics and dilutes findings. Protects the report pipeline
against old recorded runs that lack the FFT-level ``spectrum_min_hz`` filter.
"""

HARMONIC_2X: Final[float] = 2.0
"""Multiplier for the second harmonic of a fundamental frequency."""

MIN_OVERLAP_TOLERANCE: Final[float] = 0.025
"""Minimum relative tolerance used when checking whether two rotational
orders (e.g. driveshaft 1× and engine 1×) overlap in frequency."""

FREQUENCY_EPSILON_HZ: Final[float] = 1e-6
"""Tiny guard value to prevent division-by-zero in frequency ratios."""

CONFIDENCE_FLOOR: Final[float] = 0.08
"""Clamp lower bound for computed confidence so no finding is ever
completely dismissed."""

CONFIDENCE_CEILING: Final[float] = 0.97
"""Clamp upper bound for computed confidence so no finding is ever
shown as perfectly certain."""

SNR_LOG_DIVISOR: Final[float] = 2.5
"""Divisor for log1p(SNR) normalisation to [0, 1]."""

ORDER_SUPPRESS_PERSISTENT_MIN_CONF: Final[float] = 0.40
"""Minimum order-finding confidence to suppress a matching persistent peak."""

NEGLIGIBLE_STRENGTH_MAX_DB: Final[float] = 8.0
"""Upper bound (exclusive) of the negligible vibration band in dB.

Derived from the strength-labels table: the ``l1`` ("light") band starts at
this threshold, meaning values strictly below this are classified as negligible.
"""

LIGHT_STRENGTH_MAX_DB: Final[float] = 16.0
"""Upper bound (exclusive) of the light vibration band in dB.

Derived from the strength-labels table: the ``l2`` ("moderate") band starts at
this threshold, meaning values below this are classified as light or negligible.
"""

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

ORDER_MIN_MATCH_DURATION_S: Final[float] = 2.0
"""Minimum matched evidence duration required for an order finding."""

ORDER_MIN_COVERAGE_DURATION_S: Final[float] = 4.0
"""Minimum total eligible evidence duration required for an order finding."""

ORDER_MIN_CONTIGUOUS_MATCH_DURATION_S: Final[float] = 1.5
"""Minimum longest contiguous matched streak required for an order finding."""

ORDER_VARIABLE_MIN_MATCHED_SPEED_BINS: Final[int] = 2
"""Minimum matched speed bins for variable-speed order evidence without relying
on frequency-correlation rescue."""

ORDER_VARIABLE_MIN_CORRELATION: Final[float] = 0.9
"""Minimum frequency correlation for variable-speed order evidence when matched
samples do not span enough speed bins."""

ORDER_MIN_CONFIDENCE: Final[float] = 0.25
"""Minimum confidence score for an order-tracking finding to be retained."""

ORDER_CONSTANT_SPEED_MIN_MATCH_RATE: Final[float] = 0.55
"""Minimum match rate for order findings under constant-speed conditions,
where higher consistency is expected."""
