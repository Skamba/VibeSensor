from __future__ import annotations

from typing import TypedDict


class StrengthBand(TypedDict):
    key: str
    min_db: float
    min_amp: float


BANDS: tuple[StrengthBand, ...] = (
    {"key": "l1", "min_db": 10.0, "min_amp": 0.003},
    {"key": "l2", "min_db": 16.0, "min_amp": 0.006},
    {"key": "l3", "min_db": 22.0, "min_amp": 0.012},
    {"key": "l4", "min_db": 28.0, "min_amp": 0.024},
    {"key": "l5", "min_db": 34.0, "min_amp": 0.048},
)

HYSTERESIS_DB = 2.0
PERSISTENCE_TICKS = 3
DECAY_TICKS = 5


def bucket_for_strength(strength_db: float, band_rms: float) -> str | None:
    if band_rms <= 0:
        return None
    selected: str | None = None
    for band in BANDS:
        if strength_db >= band["min_db"] and band_rms >= band["min_amp"]:
            selected = band["key"]
    return selected


def band_by_key(key: str) -> StrengthBand | None:
    for band in BANDS:
        if band["key"] == key:
            return band
    return None


def band_rank(key: str) -> int:
    for idx, band in enumerate(BANDS):
        if band["key"] == key:
            return idx
    return -1
