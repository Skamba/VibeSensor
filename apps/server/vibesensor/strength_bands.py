"""Vibration-strength band definitions and bucket classification."""

from __future__ import annotations

from vibesensor.domain._vibration_strength import (
    BANDS,
    DECAY_TICKS,
    HYSTERESIS_DB,
    PERSISTENCE_TICKS,
    StrengthBand,
    band_by_key,
    band_rank,
    bucket_for_strength,
)

__all__ = [
    "BANDS",
    "DECAY_TICKS",
    "HYSTERESIS_DB",
    "PERSISTENCE_TICKS",
    "StrengthBand",
    "band_by_key",
    "band_rank",
    "bucket_for_strength",
]
