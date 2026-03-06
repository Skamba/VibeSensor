"""Vibration-strength band definitions and bucket classification.

``BANDS`` defines six strength levels (l0–l5) with minimum dB thresholds.
``bucket_for_strength`` maps a dB value to the appropriate band key.
"""

from __future__ import annotations

from typing import Final, TypedDict


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


class StrengthBand(TypedDict):
    """Typed dict for a single vibration-strength band definition."""

    key: str
    min_db: float


BANDS: Final[tuple[StrengthBand, ...]] = (
    {"key": "l0", "min_db": 0.0},
    {"key": "l1", "min_db": 8.0},
    {"key": "l2", "min_db": 16.0},
    {"key": "l3", "min_db": 26.0},
    {"key": "l4", "min_db": 36.0},
    {"key": "l5", "min_db": 46.0},
)

HYSTERESIS_DB: Final[float] = 2.0
PERSISTENCE_TICKS: Final[int] = 3
DECAY_TICKS: Final[int] = 5

# Pre-built lookup dicts for O(1) band access
_BAND_BY_KEY: dict[str, StrengthBand] = {b["key"]: b for b in BANDS}
_BAND_RANK: dict[str, int] = {b["key"]: i for i, b in enumerate(BANDS)}


def bucket_for_strength(vibration_strength_db: float) -> str:
    """Return the band key (e.g. ``"l3"``) for *vibration_strength_db*.

    Returns ``"l0"`` for sub-zero dB values (treated as negligible).
    Always returns a non-None string.
    """
    # Reverse-iterate sorted bands; first match is the highest qualifying band.
    for band in reversed(BANDS):
        if vibration_strength_db >= band["min_db"]:
            return band["key"]
    return "l0"  # sub-zero dB defaults to negligible


def band_by_key(key: str) -> StrengthBand | None:
    """Return the :class:`StrengthBand` for *key*, or ``None`` if unknown."""
    return _BAND_BY_KEY.get(key)


def band_rank(key: str) -> int:
    """Return the 0-based rank of *key* in ``BANDS``, or ``-1`` if unknown."""
    return _BAND_RANK.get(key, -1)
