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


# ---------------------------------------------------------------------------
# Certainty tier gating  (shared helper for report section suppression)
# ---------------------------------------------------------------------------

# Tier thresholds: these define the certainty boundaries for report behavior.
#
# * TIER_A_CEILING (≤ 15%): Very low certainty – insufficient data for any
#   specific diagnosis.  The report must NOT suggest repair actions or name
#   specific systems as fault sources.  Instead it guides the user toward
#   better data collection.  The 15% boundary sits above the minimum
#   confidence floor (ORDER_MIN_CONFIDENCE = 0.25 → 25% is typical low-end
#   for a surviving finding), so Tier A only fires when confidence is truly
#   marginal – e.g. single weak match with penalty cascades.
#
# * TIER_B_CEILING (≤ 40%): Low-to-medium certainty – the report may list
#   candidate systems as hypotheses but must NOT recommend repair.  Next
#   steps should be verification-oriented.
#
# * Tier C (> 40%): Sufficient certainty for the existing diagnostic report
#   behavior (system cards, repair-oriented next steps).

TIER_A_CEILING = 0.15  # Very low: suppress specific diagnoses
TIER_B_CEILING = 0.40  # Guarded: hypotheses only, verification steps


def certainty_tier(
    confidence: float,
    *,
    strength_band_key: str | None = None,
) -> str:
    """Determine report layout tier (A/B/C) for section visibility.

    NOT equivalent to ``ConfidenceAssessment.tier`` — uses different
    thresholds for report presentation purposes.

    Parameters
    ----------
    confidence:
        Analysis confidence from 0.0 to 1.0.
    strength_band_key:
        Optional vibration-strength band key (e.g. ``"negligible"``).
        When the signal is negligible the tier is capped at ``"B"`` so
        the report does not recommend specific repairs for a
        barely-detectable vibration.

    Returns
    -------
    str
        ``"A"`` (≤0.15), ``"B"`` (≤0.40), or ``"C"`` (>0.40).

    """
    # Non-finite confidence (inf/nan/-inf) must not flow through the tier
    # guards: float('inf') would pass both <= checks and return "C" (highest
    # tier), silently granting full diagnostic permissions to garbage input.
    if not _isfinite(confidence):
        confidence = 0.0
    if confidence <= TIER_A_CEILING:
        return "A"
    if confidence <= TIER_B_CEILING:
        return "B"
    # Cap at B when the vibration strength is negligible — recommending
    # specific repairs for a barely-detectable signal is misleading.
    if _is_negligible_band(strength_band_key):
        return "B"
    return "C"
