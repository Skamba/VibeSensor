"""Presentation-only labeling helpers for PDF/report rendering."""

from __future__ import annotations

import math
from collections.abc import Callable

from vibesensor.strength_bands import BANDS

__all__ = [
    "order_label_human",
    "peak_classification_text",
    "strength_label",
    "strength_text",
]

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

_ORDER_LABEL_NAMES_NL: dict[str, str] = {
    "wheel": "wielorde",
    "engine": "motororde",
    "driveshaft": "aandrijfasorde",
}
_ORDER_LABEL_NAMES_DEFAULT: dict[str, str] = {
    "wheel": "wheel order",
    "engine": "engine order",
    "driveshaft": "driveshaft order",
}

_CLASSIFICATION_I18N_KEYS: dict[str, str] = {
    "patterned": "CLASSIFICATION_PATTERNED",
    "persistent": "CLASSIFICATION_PERSISTENT",
    "transient": "CLASSIFICATION_TRANSIENT",
    "baseline_noise": "CLASSIFICATION_BASELINE_NOISE",
}


def order_label_human(lang: str, label: str) -> str:
    """Translate a language-neutral order label like ``1x wheel``."""
    names = _ORDER_LABEL_NAMES_NL if lang == "nl" else _ORDER_LABEL_NAMES_DEFAULT
    parts = label.strip().split(" ", 1)
    if len(parts) == 2:
        multiplier, base = parts
        localized = names.get(base.lower(), base)
        return f"{multiplier} {localized}"
    return label


def peak_classification_text(value: object, tr: Callable[..., str]) -> str:
    """Map a peak classification code to report text."""
    normalized = str(value or "").strip().lower()
    i18n_key = _CLASSIFICATION_I18N_KEYS.get(normalized)
    if i18n_key:
        return tr(i18n_key)
    if not normalized:
        return tr("UNKNOWN")
    return str(value).replace("_", " ").title()


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
