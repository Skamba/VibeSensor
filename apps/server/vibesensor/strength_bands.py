"""Vibration-strength band definitions and bucket classification.

``BANDS`` defines six strength levels (l0–l5) with minimum dB thresholds.
``StrengthBand`` is a frozen dataclass with comparison and containment
behaviour so callers can write ``band.contains(db)`` instead of repeating
``band["min_db"]`` dict access.
``bucket_for_strength`` maps a dB value to the appropriate band key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

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


@dataclass(frozen=True, slots=True)
class StrengthBand:
    """A single vibration-strength band definition.

    Frozen value object with comparison and containment helpers so callers
    avoid raw dict-key access.
    """

    key: str
    min_db: float

    # -- containment --------------------------------------------------------

    def contains(self, vibration_strength_db: float) -> bool:
        """Return ``True`` when *vibration_strength_db* falls at or above this band."""
        return vibration_strength_db >= self.min_db

    def exceeds_with_hysteresis(self, vibration_strength_db: float, hysteresis_db: float) -> bool:
        """Return ``True`` when *vibration_strength_db* is below ``min_db - hysteresis``."""
        return vibration_strength_db < self.min_db - hysteresis_db

    # -- dict compatibility (read-only) for downstream consumers that
    #    still index via ``band["key"]`` or ``band["min_db"]`` ---------------

    def __getitem__(self, field: str) -> object:
        if field == "key":
            return self.key
        if field == "min_db":
            return self.min_db
        raise KeyError(field)

    def get(self, field: str, default: object = None) -> object:
        """Dict-style ``.get()`` for backward compatibility."""
        try:
            return self[field]
        except KeyError:
            return default


BANDS: Final[tuple[StrengthBand, ...]] = (
    StrengthBand("l0", 0.0),
    StrengthBand("l1", 8.0),
    StrengthBand("l2", 16.0),
    StrengthBand("l3", 26.0),
    StrengthBand("l4", 36.0),
    StrengthBand("l5", 46.0),
)

HYSTERESIS_DB: Final[float] = 2.0
PERSISTENCE_TICKS: Final[int] = 3
DECAY_TICKS: Final[int] = 5

# Pre-built lookup dicts for O(1) band access
_BAND_BY_KEY: dict[str, StrengthBand] = {b.key: b for b in BANDS}
_BAND_RANK: dict[str, int] = {b.key: i for i, b in enumerate(BANDS)}


def bucket_for_strength(vibration_strength_db: float) -> str:
    """Return the band key (e.g. ``"l3"``) for *vibration_strength_db*.

    Returns ``"l0"`` for sub-zero dB values (treated as negligible).
    Always returns a non-None string.
    """
    for band in reversed(BANDS):
        if band.contains(vibration_strength_db):
            return band.key
    return "l0"


def band_by_key(key: str) -> StrengthBand | None:
    """Return the :class:`StrengthBand` for *key*, or ``None`` if unknown."""
    return _BAND_BY_KEY.get(key)


def band_rank(key: str) -> int:
    """Return the 0-based rank of *key* in ``BANDS``, or ``-1`` if unknown."""
    return _BAND_RANK.get(key, -1)
