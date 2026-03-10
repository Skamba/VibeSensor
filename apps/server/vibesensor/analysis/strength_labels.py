"""Strength and certainty labeling for diagnostic reports.

Provides user-friendly natural-language labels for vibration strength and
analysis certainty, including short generated reasons from a controlled set
of phrases.
"""

from __future__ import annotations

import math

from vibesensor.core.strength_bands import BANDS

_isfinite = math.isfinite  # local bind avoids repeated attribute lookup

CONFIDENCE_HIGH_THRESHOLD = 0.70
CONFIDENCE_MEDIUM_THRESHOLD = 0.40

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


# ---------------------------------------------------------------------------
# Certainty labels  (confidence 0–1 → label + short reason)
# ---------------------------------------------------------------------------


def _is_negligible_band(key: str | None) -> bool:
    """Return *True* when *key* denotes the negligible vibration band."""
    return (key or "").strip().lower() == "negligible"


# Controlled set of certainty reason phrases.
_CERTAINTY_REASONS: dict[str, dict[str, str]] = {
    "strong_order_match": {
        "en": "Consistent order-tracking match across speed range",
        "nl": "Consistente ordetracking-overeenkomst over snelheidsbereik",
    },
    "moderate_order_match": {
        "en": "Partial order-tracking match with some scatter",
        "nl": "Gedeeltelijke ordetracking-overeenkomst met enige spreiding",
    },
    "weak_order_match": {
        "en": "Weak pattern correlation — additional data recommended",
        "nl": "Zwakke patrooncorrelatie — aanvullende data aanbevolen",
    },
    "single_sensor": {
        "en": "Based on a single sensor location — cross-check advised",
        "nl": "Gebaseerd op één sensorlocatie — controle aanbevolen",
    },
    "narrow_speed_range": {
        "en": "Limited speed variation reduces tracking confidence",
        "nl": "Beperkte snelheidsvariatie vermindert trackingbetrouwbaarheid",
    },
    "reference_gaps": {
        "en": "Missing reference data limits pattern matching",
        "nl": "Ontbrekende referentiedata beperkt patroonvergelijking",
    },
    "good_spatial_separation": {
        "en": "Clear spatial separation between sensor locations",
        "nl": "Duidelijke ruimtelijke scheiding tussen sensorlocaties",
    },
    "weak_spatial_separation": {
        "en": "Overlapping signal levels — spatial separation is weak",
        "nl": "Overlappende signaalniveaus — ruimtelijke scheiding is zwak",
    },
    "insufficient_data": {
        "en": "Insufficient data for reliable pattern assessment",
        "nl": "Onvoldoende data voor betrouwbare patroonbeoordeling",
    },
}


def _select_reason_key(
    confidence: float,
    *,
    steady_speed: bool = False,
    weak_spatial: bool = False,
    sensor_count: int = 2,
    has_reference_gaps: bool = False,
) -> str:
    """Pick the best reason key based on context."""
    if has_reference_gaps:
        return "reference_gaps"
    if sensor_count <= 1:
        return "single_sensor"
    if steady_speed:
        return "narrow_speed_range"
    if confidence >= CONFIDENCE_MEDIUM_THRESHOLD:
        if weak_spatial:
            return "weak_spatial_separation"
        return (
            "strong_order_match"
            if confidence >= CONFIDENCE_HIGH_THRESHOLD
            else "moderate_order_match"
        )
    return "weak_order_match"


def certainty_label(
    confidence_0_to_1: float,
    *,
    lang: str = "en",
    steady_speed: bool = False,
    weak_spatial: bool = False,
    sensor_count: int = 2,
    has_reference_gaps: bool = False,
    strength_band_key: str | None = None,
) -> tuple[str, str, str, str]:
    """Return (level_key, human_label, pct_text, reason) for a confidence value.

    Parameters
    ----------
    confidence_0_to_1:
        Analysis confidence from 0.0 to 1.0.
    lang:
        ``"en"`` or ``"nl"``.
    steady_speed:
        ``True`` when the vehicle was at a consistent cruising speed during
        the run; used to select the most appropriate reason phrase.
    weak_spatial:
        ``True`` when spatial correlation across sensors is weak; shifts
        the reason phrase towards uncertainty.
    sensor_count:
        Number of active sensors; affects confidence reason phrasing.
    has_reference_gaps:
        ``True`` when known-order reference data has gaps; used to select
        a more conservative reason phrase.
    strength_band_key:
        Optional vibration-strength band key.  When set to ``"negligible"``,
        high certainty is capped to medium as a defensive label guard.

    Returns
    -------
    tuple[str, str, str, str]
        ``(level_key, human_label, pct_text, reason)``
        e.g. ``("high", "High", "80%", "Consistent order-tracking …")``.

    """
    # Guard non-finite inputs before any arithmetic so that all downstream
    # expressions (pct, threshold comparisons) work on a valid float.
    if not _isfinite(confidence_0_to_1):
        confidence_0_to_1 = 0.0
    pct = max(0.0, min(100.0, confidence_0_to_1 * 100.0))
    pct_text = f"{pct:.0f}%"

    if confidence_0_to_1 >= CONFIDENCE_HIGH_THRESHOLD:
        level_key, label_en, label_nl = "high", "High", "Hoog"
    elif confidence_0_to_1 >= CONFIDENCE_MEDIUM_THRESHOLD:
        level_key, label_en, label_nl = "medium", "Medium", "Gemiddeld"
    else:
        level_key, label_en, label_nl = "low", "Low", "Laag"
    if _is_negligible_band(strength_band_key) and level_key == "high":
        level_key, label_en, label_nl = "medium", "Medium", "Gemiddeld"

    label = label_nl if lang == "nl" else label_en
    reason_key = _select_reason_key(
        confidence_0_to_1,
        steady_speed=steady_speed,
        weak_spatial=weak_spatial,
        sensor_count=sensor_count,
        has_reference_gaps=has_reference_gaps,
    )
    reason_texts = _CERTAINTY_REASONS[reason_key]
    reason = reason_texts.get(lang) or reason_texts["en"]
    return (level_key, label, pct_text, reason)


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
#   steps should be verification-oriented.  The 40% boundary aligns with
#   the existing medium/low certainty-label cut in certainty_label().
#
# * Tier C (> 40%): Sufficient certainty for the existing diagnostic report
#   behavior (system cards, repair-oriented next steps).

TIER_A_CEILING = 0.15  # Very low: suppress specific diagnoses
TIER_B_CEILING = 0.40  # Guarded: hypotheses only, verification steps


def certainty_tier(
    confidence_0_to_1: float,
    *,
    strength_band_key: str | None = None,
) -> str:
    """Return the certainty tier key for report section gating.

    Parameters
    ----------
    confidence_0_to_1:
        Analysis confidence from 0.0 to 1.0.
    strength_band_key:
        Optional vibration-strength band key (e.g. ``"negligible"``).
        When the signal is negligible the tier is capped at ``"B"`` so
        the report does not recommend specific repairs for a
        barely-detectable vibration.

    Returns
    -------
    str
        ``"A"`` (very low), ``"B"`` (guarded), or ``"C"`` (sufficient).

    """
    # Non-finite confidence (inf/nan/-inf) must not flow through the tier
    # guards: float('inf') would pass both <= checks and return "C" (highest
    # tier), silently granting full diagnostic permissions to garbage input.
    if not _isfinite(confidence_0_to_1):
        confidence_0_to_1 = 0.0
    if confidence_0_to_1 <= TIER_A_CEILING:
        return "A"
    if confidence_0_to_1 <= TIER_B_CEILING:
        return "B"
    # Cap at B when the vibration strength is negligible — recommending
    # specific repairs for a barely-detectable signal is misleading.
    if _is_negligible_band(strength_band_key):
        return "B"
    return "C"
