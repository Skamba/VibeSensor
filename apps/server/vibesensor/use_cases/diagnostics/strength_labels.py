"""Strength labeling and certainty tier gating for diagnostic reports.

Provides user-friendly natural-language labels for vibration strength
and report layout tier gating based on analysis confidence.
"""

from __future__ import annotations

import math

from vibesensor.strength_bands import BANDS

_isfinite = math.isfinite  # local bind avoids repeated attribute lookup

# ---------------------------------------------------------------------------
# Strength labels  (vibration_strength_db → natural-language band)
# ---------------------------------------------------------------------------

_STRENGTH_LABELS_BY_BUCKET: dict[str, tuple[str, str, str]] = {
    "l0": ("negligible", "Negligible", "Verwaarloosbaar"),
    "l1": ("light", "Light", "Licht"),
    "l2": ("moderate", "Moderate", "Matig"),
    "l3": ("strong", "Strong", "Sterk"),
    "l4": ("very_strong", "Very strong", "Zeer sterk"),
    "l5": ("very_strong", "Very strong", "Zeer sterk"),
}

# Thresholds in dB for strength labels (ascending), derived from core bands.
_STRENGTH_THRESHOLDS: tuple[tuple[float, str, str, str], ...] = tuple(
    # (min_db, label_key, en_label, nl_label)
    (
        float(band["min_db"]),
        *_STRENGTH_LABELS_BY_BUCKET.get(str(band["key"]), _STRENGTH_LABELS_BY_BUCKET["l5"]),
    )
    for band in BANDS
)


def strength_label(db_value: float | None, *, lang: str = "en") -> tuple[str, str]:
    """Return (band_key, human_label) for a vibration_strength_db value.

    Parameters
    ----------
    db_value:
        Vibration strength in dB.  *None* → ``("unknown", "Unknown")``.
    lang:
        ``"en"`` or ``"nl"``.

    Returns
    -------
    tuple[str, str]
        ``(band_key, human_label)`` — e.g. ``("moderate", "Moderate")``.

    """
    if db_value is None or not _isfinite(db_value):
        return ("unknown", "Onbekend" if lang == "nl" else "Unknown")
    # Guard against an empty threshold table (e.g. BANDS tampered with at
    # test time): return unknown rather than raising IndexError.
    if not _STRENGTH_THRESHOLDS:
        return ("unknown", "Onbekend" if lang == "nl" else "Unknown")
    # Iterate from highest threshold downward; first match is the highest
    # qualifying band.  Using reversed() is correct regardless of table order
    # and avoids the silent dependency on sorted thresholds that the old
    # else:break pattern relied on.
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


def _is_negligible_band(key: str | None) -> bool:
    """Return *True* when *key* denotes the negligible vibration band."""
    return (key or "").strip().lower() == "negligible"
