"""Shared constants used across the findings subpackage."""

from __future__ import annotations

from ..strength_labels import _STRENGTH_THRESHOLDS

# Upper-boundary indices into _STRENGTH_THRESHOLDS for the negligible and light
# bands.  The BANDS tuple has: index 0 = l0 "negligible" (0 dB), index 1 = l1
# "light" (8 dB), index 2 = l2 "moderate" (16 dB).
# Using index 1 gives 8.0 dB — the minimum threshold of "light", which is the
# exclusive upper bound of the negligible band.  Similarly, index 2 gives 16.0
# dB — the exclusive upper bound of the light band.
_NEGLIGIBLE_UPPER_BAND_INDEX = 1  # _STRENGTH_THRESHOLDS[1][0] == 8.0 dB
_LIGHT_UPPER_BAND_INDEX = 2  # _STRENGTH_THRESHOLDS[2][0] == 16.0 dB

# Strength thresholds derived from the global strength-labels table.
_NEGLIGIBLE_STRENGTH_MAX_DB = (
    float(_STRENGTH_THRESHOLDS[_NEGLIGIBLE_UPPER_BAND_INDEX][0])
    if len(_STRENGTH_THRESHOLDS) > _NEGLIGIBLE_UPPER_BAND_INDEX
    else 8.0
)
_LIGHT_STRENGTH_MAX_DB = (
    float(_STRENGTH_THRESHOLDS[_LIGHT_UPPER_BAND_INDEX][0])
    if len(_STRENGTH_THRESHOLDS) > _LIGHT_UPPER_BAND_INDEX
    else 16.0
)

# Minimum order-finding confidence to suppress a matching persistent-peak.
_ORDER_SUPPRESS_PERSISTENT_MIN_CONF = 0.40

# ── SNR and confidence scoring constants ────────────────────────────────
# Divisor for log1p(SNR) normalisation to [0, 1].
_SNR_LOG_DIVISOR = 2.5
# Clamp bounds for computed confidence so no finding is ever shown as
# perfectly certain or completely dismissed.
_CONFIDENCE_FLOOR = 0.08
_CONFIDENCE_CEILING = 0.97
