"""Analysis and scoring constants shared by diagnostics and reporting."""

from __future__ import annotations

from typing import Final

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

MIN_ORDER_TRACKING_SLOPE: Final[float] = 0.5
"""Least slope of matched vs predicted frequency for matches to count as an order.

An order's peaks move one-for-one with its prediction as speed changes; a
fixed-frequency tone (body resonance, engine idle in neutral) that the
prediction sweeps past stays put, giving a slope near 0 (see
``domain.order_match.frequency_tracking_slope``). Judged only when the speed
really changed (``domain.order_match.trend_moves``): order hypotheses over the
whole run, the guided coast-down test inside the coast-down."""

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

STEADY_SPEED_STDDEV_RAMP_KMH: Final[float] = 1.0
STEADY_SPEED_RANGE_RAMP_KMH: Final[float] = 4.0
CONSTANT_SPEED_STDDEV_RAMP_KMH: Final[float] = 0.5
"""How far past the steady/constant limits order confidence still treats the
speed as partly steady/constant (``speed_steadiness``, ``speed_constancy``), so
a drive a hair over a limit is scored almost as one just under it."""

ORDER_MIN_MATCH_POINTS: Final[int] = 4
"""Minimum number of matched sample points for an order finding to be emitted."""

ORDER_MIN_COVERAGE_POINTS: Final[int] = 6
"""Minimum number of coverage points (samples with valid speed and peak data)
for an order finding to be considered."""

ORDER_MIN_MATCH_DURATION_S: Final[float] = 2.0
"""Minimum matched evidence duration required for an order finding."""

ORDER_MIN_COVERAGE_DURATION_S: Final[float] = 4.0
"""Minimum total eligible evidence duration required for an order finding."""

ORDER_VARIABLE_MIN_MATCHED_SPEED_BINS: Final[int] = 2
"""Minimum matched speed bins for variable-speed order evidence without relying
on frequency-correlation rescue."""

ORDER_VARIABLE_MIN_CORRELATION: Final[float] = 0.9
"""Minimum frequency correlation for variable-speed order evidence when matched
samples do not span enough speed bins."""

ORDER_LINE_WIDTH_REL: Final[float] = 0.015
"""Half-width of an order's spectral line, relative to its frequency. A
rotating order is a line that follows its prediction (times one constant
factor, for a slightly-off tyre size or ratio) to within the speed reading's
error; see "Order lines" in docs/order_tracking.md."""

ORDER_LINE_WIDTH_MIN_BINS: Final[float] = 0.5
"""Minimum line half-width in FFT bins: peaks sit on bin centres."""

ORDER_LINE_MIN_SHARE: Final[float] = 0.5
"""Share of a sensor's clear matches that must sit on one line for them to be
the order rather than broadband content (a road-excited resonance hump) that
fills the tolerance window."""

ORDER_LINE_MIN_POINTS: Final[int] = 12
"""Fewest judged clear matches in a group before the line test judges it; a
sensor with fewer clear matches is judged together with the others."""

ORDER_LINE_MIN_TOLERANCE_WIDTHS: Final[float] = 4.0
"""The line test places the line only on matches whose tolerance window is at
least this many line widths wide; a narrower window holds too little scatter to
tell a line from it, though a match there is still held against the line."""

ORDER_MIN_CONFIDENCE: Final[float] = 0.25
"""Minimum confidence score for an order-tracking finding to be retained."""

ORDER_MIN_MATCH_RATE: Final[float] = 0.25
"""Minimum effective match rate for an order finding with the speed varying."""

ORDER_CONSTANT_SPEED_MIN_MATCH_RATE: Final[float] = 0.55
"""Minimum match rate for order findings under constant-speed conditions,
where higher consistency is expected."""
