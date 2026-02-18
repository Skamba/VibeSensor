from __future__ import annotations

from typing import TypedDict


class StrengthBand(TypedDict):
    key: str
    min_db: float


BANDS: tuple[StrengthBand, ...] = (
    {"key": "l1", "min_db": 10.0},
    {"key": "l2", "min_db": 16.0},
    {"key": "l3", "min_db": 22.0},
    {"key": "l4", "min_db": 28.0},
    {"key": "l5", "min_db": 34.0},
)

HYSTERESIS_DB = 2.0
PERSISTENCE_TICKS = 3
DECAY_TICKS = 5


def bucket_for_strength(vibration_strength_db: float) -> str | None:
    selected: str | None = None
    for band in BANDS:
        if vibration_strength_db >= band["min_db"]:
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
