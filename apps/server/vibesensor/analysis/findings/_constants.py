"""Shared constants used across the findings subpackage."""

from __future__ import annotations

from ..strength_labels import _STRENGTH_THRESHOLDS

# Strength thresholds derived from the global strength-labels table.
_NEGLIGIBLE_STRENGTH_MAX_DB = (
    float(_STRENGTH_THRESHOLDS[1][0]) if len(_STRENGTH_THRESHOLDS) > 1 else 8.0
)
_LIGHT_STRENGTH_MAX_DB = (
    float(_STRENGTH_THRESHOLDS[2][0]) if len(_STRENGTH_THRESHOLDS) > 2 else 16.0
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
