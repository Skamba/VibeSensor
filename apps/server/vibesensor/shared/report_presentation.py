"""Canonical report presentation helpers shared by history prep and PDF mapping."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence

from vibesensor.domain import Finding, LocationIntensitySummary, TestRun, VibrationSource
from vibesensor.report_i18n import human_location, location_candidates
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
from vibesensor.shared.constants.phases import PHASE_I18N_KEYS
from vibesensor.strength_bands import BANDS

__all__ = [
    "action_status_text",
    "append_unique_line",
    "candidate_signal_text",
    "coverage_label",
    "coverage_notes",
    "display_location",
    "display_phase_label",
    "display_speed_band",
    "has_source_overlap",
    "human_source",
    "is_transient_primary",
    "location_confidence_text",
    "order_label_human",
    "peak_classification_text",
    "presented_location_confidence_key",
    "runner_up_corner",
    "source_with_confidence",
    "strength_label",
    "strength_text",
    "uses_shared_overlap_wording",
]

_isfinite = math.isfinite
_logger = logging.getLogger(__name__)

_SOURCE_I18N_KEYS: dict[VibrationSource, str] = {
    VibrationSource.WHEEL_TIRE: "SOURCE_WHEEL_TIRE",
    VibrationSource.DRIVELINE: "SOURCE_DRIVELINE",
    VibrationSource.ENGINE: "SOURCE_ENGINE",
    VibrationSource.BODY_RESONANCE: "SOURCE_BODY_RESONANCE",
    VibrationSource.TRANSIENT_IMPACT: "SOURCE_TRANSIENT_IMPACT",
    VibrationSource.BASELINE_NOISE: "SOURCE_BASELINE_NOISE",
    VibrationSource.UNKNOWN_RESONANCE: "SOURCE_UNKNOWN_RESONANCE",
    VibrationSource.UNKNOWN: "UNKNOWN",
}

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
    "wheel order": "wielorde",
    "engine": "motororde",
    "engine order": "motororde",
    "driveshaft": "aandrijfasorde",
    "driveshaft order": "aandrijfasorde",
}
_ORDER_LABEL_NAMES_DEFAULT: dict[str, str] = {
    "wheel": "wheel order",
    "wheel order": "wheel order",
    "engine": "engine order",
    "engine order": "engine order",
    "driveshaft": "driveshaft order",
    "driveshaft order": "driveshaft order",
}

_CLASSIFICATION_I18N_KEYS: dict[str, str] = {
    "patterned": "CLASSIFICATION_PATTERNED",
    "persistent": "CLASSIFICATION_PERSISTENT",
    "transient": "CLASSIFICATION_TRANSIENT",
    "baseline_noise": "CLASSIFICATION_BASELINE_NOISE",
}


def action_status_text(action_status_key: str, *, tr: Callable[..., str]) -> str:
    keys = {
        "action_ready": "REPORT_ACTION_STATUS_READY",
        "action_ready_caution": "REPORT_ACTION_STATUS_READY_CAUTION",
        "recapture_before_acting": "REPORT_ACTION_STATUS_RECAPTURE",
    }
    return tr(keys.get(action_status_key, "REPORT_ACTION_STATUS_RECAPTURE"))


def location_confidence_text(location_confidence_key: str, *, tr: Callable[..., str]) -> str:
    keys = {
        "strong": "REPORT_LOCATION_CONFIDENCE_STRONG",
        "limited": "REPORT_LOCATION_CONFIDENCE_LIMITED",
        "mixed": "REPORT_LOCATION_CONFIDENCE_MIXED",
        "weak": "REPORT_LOCATION_CONFIDENCE_WEAK",
    }
    return tr(keys.get(location_confidence_key, "REPORT_LOCATION_CONFIDENCE_MIXED"))


def presented_location_confidence_key(
    *,
    action_status_key: str,
    location_confidence_key: str,
) -> str:
    if action_status_key == "action_ready_caution" and location_confidence_key != "weak":
        return "limited"
    return location_confidence_key


def display_location(value: object, *, short: bool = True, tr: Callable[..., str]) -> str:
    text = str(value or "").strip()
    if not text:
        return tr("UNKNOWN")
    lang = _display_lang(tr)
    candidates = location_candidates(text)
    if len(candidates) == 2:
        return tr(
            "REPORT_LOCATION_MIXED_SIGNAL_BETWEEN",
            first_location=human_location(candidates[0], short=short, lang=lang),
            second_location=human_location(candidates[1], short=short, lang=lang),
        )
    if len(candidates) > 2:
        return tr(
            "REPORT_LOCATION_MIXED_SIGNAL_LIST",
            locations=", ".join(
                human_location(candidate, short=short, lang=lang) for candidate in candidates
            ),
        )
    return human_location(text, short=short, lang=lang)


def _display_lang(tr: Callable[..., str]) -> str:
    try:
        return "nl" if tr("UNKNOWN") == "Onbekend" else "en"
    except Exception:
        return "en"


def order_label_human(lang: str, label: str) -> str:
    """Translate a language-neutral order label like ``1x wheel``."""
    if "," in label:
        return ", ".join(
            order_label_human(lang, part.strip()) for part in label.split(",") if part.strip()
        )
    names = _ORDER_LABEL_NAMES_NL if lang == "nl" else _ORDER_LABEL_NAMES_DEFAULT
    parts = label.strip().split(" ", 1)
    if len(parts) == 2:
        multiplier, base = parts
        localized = names.get(base.lower(), base)
        return f"{multiplier} {localized}"
    return label


def display_speed_band(value: object, *, tr: Callable[..., str]) -> str:
    """Render a persisted speed-band label in the active report language."""
    text = str(value or "").strip()
    if not text:
        return ""
    if _display_lang(tr) == "nl":
        return text.replace("km/h", "km/u")
    return text


def display_phase_label(value: object, *, tr: Callable[..., str]) -> str | None:
    """Render a persisted driving-phase label in the active report language."""
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return None
    i18n_key = PHASE_I18N_KEYS.get(normalized)
    if i18n_key:
        return tr(i18n_key)
    return normalized.replace("_", " ").title()


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


def coverage_label(
    *,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    missing_locations: Sequence[str],
    partial_locations: Sequence[str],
    tr: Callable[..., str],
) -> str:
    expected = len(expected_locations) or len(active_locations)
    active = len(active_locations)
    if expected <= 0:
        return tr("REPORT_COVERAGE_UNKNOWN")
    if not missing_locations and not partial_locations:
        return tr("REPORT_COVERAGE_ALL_SEEN", active=active, expected=expected)
    if partial_locations:
        return tr("REPORT_COVERAGE_PARTIAL", active=active, expected=expected)
    return tr("REPORT_COVERAGE_ACTIVE_OF_EXPECTED", active=active, expected=expected)


def coverage_notes(
    *,
    missing_locations: Sequence[str],
    partial_locations: Sequence[str],
    tr: Callable[..., str],
) -> tuple[str, ...]:
    notes: list[str] = []
    if missing_locations:
        notes.append(
            tr(
                "REPORT_COVERAGE_NOTE_MISSING",
                locations=", ".join(
                    display_location(location, short=False, tr=tr) for location in missing_locations
                ),
            ),
        )
    if partial_locations:
        notes.append(
            tr(
                "REPORT_COVERAGE_NOTE_PARTIAL",
                locations=", ".join(
                    display_location(location, short=False, tr=tr) for location in partial_locations
                ),
            ),
        )
    if not notes:
        notes.append(tr("REPORT_COVERAGE_NOTE_COMPLETE"))
    return tuple(notes)


def human_source(source: object, *, tr: Callable[[str], str]) -> str:
    """Resolve a source code to its user-facing label."""
    raw = str(source or "").strip().lower()
    try:
        key = VibrationSource(raw)
    except ValueError:
        _logger.warning(
            "Unrecognized vibration source %r; falling back to titlecase",
            raw,
        )
        return raw.replace("_", " ").title() if raw else tr("UNKNOWN")
    return tr(_SOURCE_I18N_KEYS.get(key, "UNKNOWN"))


def source_with_confidence(finding: Finding, *, tr: Callable[..., str]) -> str:
    confidence = (
        finding.confidence_assessment.pct_text
        if finding.confidence_assessment is not None
        else finding.confidence_pct_text
    )
    return tr(
        "REPORT_SOURCE_WITH_CONFIDENCE",
        source=human_source(finding.suspected_source, tr=tr),
        confidence=confidence,
    )


def runner_up_corner(
    active_sensor_intensity: Sequence[LocationIntensitySummary],
    *,
    tr: Callable[..., str],
) -> str | None:
    ranked_rows = sorted(
        active_sensor_intensity,
        key=lambda row: (
            row.p95_intensity_db if row.p95_intensity_db is not None else float("-inf"),
            row.mean_intensity_db if row.mean_intensity_db is not None else float("-inf"),
        ),
        reverse=True,
    )
    if len(ranked_rows) < 2:
        return None
    return display_location(ranked_rows[1].location, tr=tr)


def append_unique_line(lines: list[str], text: object) -> None:
    value = str(text or "").strip()
    if not value:
        return
    normalized = value.rstrip(".").casefold()
    if any(existing.rstrip(".").casefold() == normalized for existing in lines):
        return
    lines.append(value)


def candidate_signal_text(finding: Finding, *, tr: Callable[..., str]) -> str:
    if finding.signature_labels:
        lang = _display_lang(tr)
        return ", ".join(
            order_label_human(lang, str(label)) for label in finding.signature_labels[:2]
        )
    if finding.order:
        return order_label_human(_display_lang(tr), finding.order)
    if finding.frequency_hz is not None:
        return f"{finding.frequency_hz:.1f} Hz"
    return tr("REPORT_SIGNAL_FALLBACK")


def uses_shared_overlap_wording(
    primary_finding: Finding,
    alternative_finding: Finding,
    *,
    tr: Callable[..., str],
) -> bool:
    sources = {
        primary_finding.source_normalized,
        alternative_finding.source_normalized,
    }
    if sources != {VibrationSource.WHEEL_TIRE, VibrationSource.DRIVELINE}:
        return False
    primary_location = str(primary_finding.strongest_location or "").strip()
    alternative_location = str(alternative_finding.strongest_location or "").strip()
    if not primary_location or not alternative_location:
        return False
    return (
        display_location(primary_location, short=False, tr=tr).strip().lower()
        == display_location(alternative_location, short=False, tr=tr).strip().lower()
    )


def has_source_overlap(aggregate: TestRun, *, tr: Callable[..., str]) -> bool:
    ranked = list(aggregate.effective_top_causes()[:2])
    if len(ranked) < 2:
        return False
    return uses_shared_overlap_wording(ranked[0], ranked[1], tr=tr)


def is_transient_primary(primary_candidate_facts: PrimaryReportFacts) -> bool:
    finding = primary_candidate_facts.domain_primary
    if finding is None:
        return False
    source = str(finding.suspected_source or "").strip().lower()
    classification = str(finding.peak_classification or "").strip().lower()
    return source == "transient_impact" or classification == "transient"
