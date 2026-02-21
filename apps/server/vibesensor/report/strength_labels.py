"""Strength and certainty labeling for diagnostic reports.

Provides user-friendly natural-language labels for vibration strength and
analysis certainty, including short generated reasons from a controlled set
of phrases.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Strength labels  (vibration_strength_db → natural-language band)
# ---------------------------------------------------------------------------

# Thresholds in dB for strength bands (ascending).
_STRENGTH_THRESHOLDS: list[tuple[float, str, str, str]] = [
    # (min_db, band_key, en_label, nl_label)
    (0.0, "negligible", "Negligible", "Verwaarloosbaar"),
    (8.0, "light", "Light", "Licht"),
    (16.0, "moderate", "Moderate", "Matig"),
    (26.0, "strong", "Strong", "Sterk"),
    (36.0, "very_strong", "Very strong", "Zeer sterk"),
]


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
    if db_value is None:
        return ("unknown", "Onbekend" if lang == "nl" else "Unknown")
    label_idx = 3 if lang == "nl" else 2
    result = _STRENGTH_THRESHOLDS[0]
    for threshold in _STRENGTH_THRESHOLDS:
        if db_value >= threshold[0]:
            result = threshold
        else:
            break
    return (result[1], result[label_idx])


def strength_text(
    db_value: float | None,
    *,
    lang: str = "en",
    peak_amp_g: float | None = None,
) -> str:
    """Return a formatted strength string like ``'Moderate (22.0 dB · 0.032 g peak)'``."""
    _, label = strength_label(db_value, lang=lang)
    if db_value is None:
        return label
    if peak_amp_g is not None:
        return f"{label} ({db_value:.1f} dB · {peak_amp_g:.3f} g peak)"
    return f"{label} ({db_value:.1f} dB)"


# ---------------------------------------------------------------------------
# Certainty labels  (confidence 0–1 → label + short reason)
# ---------------------------------------------------------------------------

# Controlled set of certainty reason phrases.
_CERTAINTY_REASONS: dict[str, dict[str, str]] = {
    "strong_order_match": {
        "en": "Consistent order-tracking match across speed range",
        "nl": "Consistente ordetracking-match over snelheidsbereik",
    },
    "moderate_order_match": {
        "en": "Partial order-tracking match with some scatter",
        "nl": "Gedeeltelijke ordetracking-match met enige spreiding",
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
        "nl": "Beperkte snelheidsvariatie vermindert tracking-betrouwbaarheid",
    },
    "reference_gaps": {
        "en": "Missing reference data limits pattern matching",
        "nl": "Ontbrekende referentiedata beperkt patroonmatching",
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
    if confidence >= 0.70:
        if weak_spatial:
            return "weak_spatial_separation"
        return "strong_order_match"
    if confidence >= 0.40:
        if weak_spatial:
            return "weak_spatial_separation"
        return "moderate_order_match"
    return "weak_order_match"


def certainty_label(
    confidence_0_to_1: float,
    *,
    lang: str = "en",
    steady_speed: bool = False,
    weak_spatial: bool = False,
    sensor_count: int = 2,
    has_reference_gaps: bool = False,
) -> tuple[str, str, str, str]:
    """Return (level_key, human_label, pct_text, reason) for a confidence value.

    Parameters
    ----------
    confidence_0_to_1:
        Analysis confidence from 0.0 to 1.0.
    lang:
        ``"en"`` or ``"nl"``.
    steady_speed / weak_spatial / sensor_count / has_reference_gaps:
        Context flags used to select the most appropriate reason phrase.

    Returns
    -------
    tuple[str, str, str, str]
        ``(level_key, human_label, pct_text, reason)``
        e.g. ``("high", "High", "80%", "Consistent order-tracking …")``.
    """
    pct = max(0.0, min(100.0, confidence_0_to_1 * 100.0))
    pct_text = f"{pct:.0f}%"

    if confidence_0_to_1 >= 0.70:
        level_key, label_en, label_nl = "high", "High", "Hoog"
    elif confidence_0_to_1 >= 0.40:
        level_key, label_en, label_nl = "medium", "Medium", "Gemiddeld"
    else:
        level_key, label_en, label_nl = "low", "Low", "Laag"

    label = label_nl if lang == "nl" else label_en
    reason_key = _select_reason_key(
        confidence_0_to_1,
        steady_speed=steady_speed,
        weak_spatial=weak_spatial,
        sensor_count=sensor_count,
        has_reference_gaps=has_reference_gaps,
    )
    reason = _CERTAINTY_REASONS[reason_key][lang]
    return (level_key, label, pct_text, reason)
