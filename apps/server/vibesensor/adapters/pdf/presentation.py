"""Presentation-only strength labeling helpers for PDF/report rendering."""

from __future__ import annotations

import math

from vibesensor.strength_bands import BANDS

__all__ = ["strength_label", "strength_text"]

_isfinite = math.isfinite

_STRENGTH_LABELS_BY_BUCKET: dict[str, tuple[str, str, str]] = {
    "l0": ("negligible", "Negligible", "Verwaarloosbaar"),
    "l1": ("light", "Light", "Licht"),
    "l2": ("moderate", "Moderate", "Matig"),
    "l3": ("strong", "Strong", "Sterk"),
    "l4": ("very_strong", "Very strong", "Zeer sterk"),
    "l5": ("very_strong", "Very strong", "Zeer sterk"),
}

_STRENGTH_THRESHOLDS: tuple[tuple[float, str, str, str], ...] = tuple(
    (
        float(band["min_db"]),
        *_STRENGTH_LABELS_BY_BUCKET.get(str(band["key"]), _STRENGTH_LABELS_BY_BUCKET["l5"]),
    )
    for band in BANDS
)


def strength_label(db_value: float | None, *, lang: str = "en") -> tuple[str, str]:
    """Return ``(band_key, human_label)`` for a vibration-strength dB value."""
    if db_value is None or not _isfinite(db_value):
        return ("unknown", "Onbekend" if lang == "nl" else "Unknown")
    if not _STRENGTH_THRESHOLDS:
        return ("unknown", "Onbekend" if lang == "nl" else "Unknown")
    result: tuple[float, str, str, str] = _STRENGTH_THRESHOLDS[0]
    for threshold in reversed(_STRENGTH_THRESHOLDS):
        if db_value >= threshold[0]:
            result = threshold
            break
    return (result[1], result[3] if lang == "nl" else result[2])


def strength_text(
    db_value: float | None,
    *,
    lang: str = "en",
) -> str:
    """Return a formatted strength string like ``'Moderate (22.0 dB)'``."""
    _, label = strength_label(db_value, lang=lang)
    if db_value is None:
        return label
    return f"{label} ({db_value:.1f} dB)"
