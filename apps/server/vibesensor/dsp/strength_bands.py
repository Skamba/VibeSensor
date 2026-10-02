"""Vibration-strength band definitions and bucket classification.

``BANDS`` defines six strength levels (l0–l5) with minimum dB thresholds.
``bucket_for_strength`` maps a dB value to the appropriate band key.
"""

from __future__ import annotations

from typing import Final, TypedDict

import numpy as np
import numpy.typing as npt

__all__ = [
    "BANDS",
    "StrengthBand",
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

_BAND_KEYS: Final[tuple[str, ...]] = tuple(b["key"] for b in BANDS)
_BAND_MIN_DB_VALUES: Final[npt.NDArray[np.float64]] = np.array(
    [b["min_db"] for b in BANDS],
    dtype=np.float64,
)


def _buckets_for_strength_db_aligned(
    vibration_strength_db_values: npt.NDArray[np.float64],
) -> list[str]:
    indexes = np.searchsorted(
        _BAND_MIN_DB_VALUES,
        vibration_strength_db_values,
        side="right",
    ).astype(np.intp, copy=False)
    indexes -= 1
    np.maximum(indexes, 0, out=indexes)
    np.minimum(indexes, len(_BAND_KEYS) - 1, out=indexes)
    return [_BAND_KEYS[int(idx)] for idx in indexes]


def bucket_for_strength(vibration_strength_db: float) -> str:
    """Return the band key (e.g. ``"l3"``) for *vibration_strength_db*.

    Returns ``"l0"`` for sub-zero dB values (treated as negligible).
    Always returns a non-None string.
    """
    for band in reversed(BANDS):
        if vibration_strength_db >= band["min_db"]:
            return band["key"]
    return "l0"
