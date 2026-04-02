"""Canonical analysis-settings schema and boundary sanitization helpers."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping

from vibesensor.domain._numeric import coerce_float
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot

LOGGER = logging.getLogger(__name__)

ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS = AnalysisSettingsSnapshot.POSITIVE_REQUIRED_KEYS
ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS = AnalysisSettingsSnapshot.NON_NEGATIVE_KEYS
ANALYSIS_SETTINGS_BOUNDS = AnalysisSettingsSnapshot._BOUNDS
ANALYSIS_SETTINGS_DEFAULTS = AnalysisSettingsSnapshot.DEFAULTS
ANALYSIS_SETTINGS_FIELDS: tuple[str, ...] = tuple(ANALYSIS_SETTINGS_DEFAULTS)

__all__ = [
    "ANALYSIS_SETTINGS_BOUNDS",
    "ANALYSIS_SETTINGS_DEFAULTS",
    "ANALYSIS_SETTINGS_FIELDS",
    "ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS",
    "ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS",
    "sanitize_analysis_settings",
]


def sanitize_analysis_settings(
    payload: Mapping[str, object],
    allowed_keys: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Validate and normalize flat analysis-settings payloads."""

    allowed = allowed_keys if allowed_keys is not None else ANALYSIS_SETTINGS_DEFAULTS
    out: dict[str, float] = {}
    for key in allowed:
        raw = payload.get(key)
        if raw is None:
            continue
        try:
            value = coerce_float(raw)
        except (TypeError, ValueError):
            LOGGER.debug("Dropping non-numeric analysis setting %s=%r", key, raw)
            continue
        if not math.isfinite(value):
            LOGGER.debug("Dropping non-finite analysis setting %s=%r", key, raw)
            continue
        if key in ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS and value <= 0:
            LOGGER.debug("Dropping non-positive analysis setting %s=%r", key, value)
            continue
        if key in ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS and value < 0:
            LOGGER.debug("Dropping negative analysis setting %s=%r", key, value)
            continue
        bounds = ANALYSIS_SETTINGS_BOUNDS.get(key)
        if bounds is not None:
            lower, upper = bounds
            if value < lower:
                LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, lower)
                value = lower
            elif value > upper:
                LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, upper)
                value = upper
        out[key] = value
    attempted = [key for key in allowed if payload.get(key) is not None]
    if attempted and not out:
        LOGGER.warning(
            "sanitize_analysis_settings: all %d submitted keys were invalid and dropped: %s",
            len(attempted),
            attempted,
        )
    return out
