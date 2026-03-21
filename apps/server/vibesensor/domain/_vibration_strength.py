"""Domain-owned vibration-strength helpers for run-capture value objects."""

from __future__ import annotations

from math import isfinite, log10
from typing import Final, TypedDict

__all__ = [
    "BANDS",
    "DECAY_TICKS",
    "HYSTERESIS_DB",
    "PERSISTENCE_TICKS",
    "StrengthBand",
    "STRENGTH_EPSILON_FLOOR_RATIO",
    "STRENGTH_EPSILON_MIN_G",
    "band_by_key",
    "band_rank",
    "bucket_for_strength",
    "compute_db",
    "compute_db_or_none",
    "vibration_strength_db_scalar",
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

STRENGTH_EPSILON_MIN_G: Final[float] = 1e-9
STRENGTH_EPSILON_FLOOR_RATIO: Final[float] = 0.05

_BAND_BY_KEY: dict[str, StrengthBand] = {band["key"]: band for band in BANDS}
_BAND_RANK: dict[str, int] = {band["key"]: index for index, band in enumerate(BANDS)}


def bucket_for_strength(vibration_strength_db: float) -> str:
    """Return the band key (for example ``"l3"``) for *vibration_strength_db*."""
    for band in reversed(BANDS):
        if vibration_strength_db >= band["min_db"]:
            return band["key"]
    return "l0"


def band_by_key(key: str) -> StrengthBand | None:
    """Return the strength band definition for *key*, or ``None`` if unknown."""
    return _BAND_BY_KEY.get(key)


def band_rank(key: str) -> int:
    """Return the ordinal rank of *key* in ``BANDS``, or ``-1`` if unknown."""
    return _BAND_RANK.get(key, -1)


def vibration_strength_db_scalar(
    *,
    peak_band_rms_amp_g: float,
    floor_amp_g: float,
    epsilon_g: float | None = None,
) -> float:
    """Compute vibration strength in dB: ``20*log10((peak+eps)/(floor+eps))``."""
    floor_raw = float(floor_amp_g)
    band_raw = float(peak_band_rms_amp_g)
    floor = max(0.0, floor_raw) if isfinite(floor_raw) else 0.0
    band = max(0.0, band_raw) if isfinite(band_raw) else 0.0
    epsilon = (
        max(STRENGTH_EPSILON_MIN_G, floor * STRENGTH_EPSILON_FLOOR_RATIO)
        if epsilon_g is None
        else max(STRENGTH_EPSILON_MIN_G, float(epsilon_g))
    )
    return 20.0 * log10((band + epsilon) / (floor + epsilon))


def compute_db(peak_amplitude_g: float, noise_floor_g: float) -> float:
    """Compute vibration strength in dB from an amplitude pair."""
    return vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak_amplitude_g,
        floor_amp_g=noise_floor_g,
    )


def compute_db_or_none(
    peak_amplitude_g: float | None,
    noise_floor_g: float | None,
) -> float | None:
    """Like :func:`compute_db` but returns ``None`` when either input is ``None``."""
    if peak_amplitude_g is None or noise_floor_g is None:
        return None
    return vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak_amplitude_g,
        floor_amp_g=noise_floor_g,
    )
