"""Canonical report presentation helpers shared by history prep and PDF mapping."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence

from vibesensor.domain import Finding, LocationIntensitySummary, TestRun, VibrationSource
from vibesensor.domain.diagnosis_assessment import LEGACY_CONTEXT_CAVEAT_KEY
from vibesensor.report_i18n import human_location, location_candidates
from vibesensor.shared.boundaries.reporting.confidence_facts import ReportConfidenceFacts
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
from vibesensor.strength_bands import BANDS

__all__ = [
    "action_status_text",
    "append_unique_line",
    "candidate_signal_text",
    "confidence_caveat_text",
    "confidence_pct_text",
    "confidence_reason_text",
    "confidence_snapshot_text",
    "coverage_label",
    "coverage_notes",
    "display_location",
    "first_confidence_reason_clause",
    "has_source_overlap",
    "human_source",
    "is_transient_primary",
    "location_confidence_text",
    "order_label_human",
    "peak_classification_text",
    "presented_location_confidence_key",
    "proof_caveat_text",
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


def first_confidence_reason_clause(primary_candidate_facts: PrimaryReportFacts) -> str | None:
    finding = primary_candidate_facts.domain_primary
    if finding is None or finding.confidence_assessment is None:
        return None
    for clause in str(finding.confidence_assessment.reason or "").split(";"):
        text = clause.strip().rstrip(".")
        if text:
            return text
    return None


def display_location(value: object, *, short: bool = True, tr: Callable[..., str]) -> str:
    text = str(value or "").strip()
    if not text:
        return tr("UNKNOWN")
    candidates = location_candidates(text)
    if len(candidates) == 2:
        return tr(
            "REPORT_LOCATION_MIXED_SIGNAL_BETWEEN",
            first_location=human_location(candidates[0], short=short),
            second_location=human_location(candidates[1], short=short),
        )
    if len(candidates) > 2:
        return tr(
            "REPORT_LOCATION_MIXED_SIGNAL_LIST",
            locations=", ".join(human_location(candidate, short=short) for candidate in candidates),
        )
    return human_location(text, short=short)


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


def confidence_pct_text(finding: Finding) -> str:
    if finding.confidence_assessment is not None:
        return finding.confidence_assessment.pct_text
    return finding.confidence_pct_text


def confidence_reason_text(
    confidence_facts: ReportConfidenceFacts,
    *,
    tr: Callable[..., str],
) -> str:
    if confidence_facts.uses_summary_fallback:
        return str(confidence_facts.fallback_reason or "").strip() or (
            tr("REPORT_CONFIDENCE_CAVEAT_SUMMARY_ONLY")
            if confidence_facts.data_basis == "summary_only"
            else ""
        )
    strengths = _confidence_signal_texts(confidence_facts, tr=tr)
    caveats = _confidence_caveat_texts(confidence_facts, tr=tr)
    strength = strengths[0] if strengths else ""
    caveat = "; ".join(caveats[:2])
    if confidence_facts.label_key == "CONFIDENCE_LOW" and caveat and strength:
        return tr(
            "REPORT_CONFIDENCE_REASON_LIMITED_SUPPORT",
            caveat=caveat,
            strength=strength,
        )
    if strength and caveat:
        return tr(
            "REPORT_CONFIDENCE_REASON_WITH_CAVEAT",
            strength=strength,
            caveat=caveat,
        )
    return strength or caveat


def confidence_snapshot_text(
    confidence_facts: ReportConfidenceFacts,
    *,
    tr: Callable[..., str],
) -> str:
    label = tr(confidence_facts.label_key)
    reason = confidence_reason_text(confidence_facts, tr=tr)
    if not reason:
        return f"{label} ({confidence_facts.pct_text})"
    return f"{label} ({confidence_facts.pct_text}) — {reason}"


def confidence_caveat_text(
    confidence_facts: ReportConfidenceFacts,
    *,
    tr: Callable[..., str],
) -> str | None:
    if confidence_facts.uses_summary_fallback:
        if confidence_facts.data_basis == "summary_only":
            return tr("REPORT_CONFIDENCE_CAVEAT_SUMMARY_ONLY")
        return None
    caveats = _confidence_caveat_texts(confidence_facts, tr=tr)
    if not caveats:
        return None
    return "; ".join(caveats[:2])


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
    return tr(
        "REPORT_SOURCE_WITH_CONFIDENCE",
        source=human_source(finding.suspected_source, tr=tr),
        confidence=confidence_pct_text(finding),
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


def proof_caveat_text(
    *,
    confidence_facts: ReportConfidenceFacts,
    action_status_key: str,
    location_confidence_key: str,
    tr: Callable[..., str],
) -> str | None:
    if action_status_key == "action_ready_caution":
        return None
    reason = (
        confidence_caveat_text(confidence_facts, tr=tr)
        if action_status_key != "action_ready"
        else None
    )
    if reason:
        return reason
    if location_confidence_key == "weak":
        return tr("REPORT_PROOF_CAVEAT_WEAK")
    if location_confidence_key == "mixed":
        return tr("REPORT_PROOF_CAVEAT_MIXED")
    return None


def _confidence_signal_texts(
    confidence_facts: ReportConfidenceFacts,
    *,
    tr: Callable[..., str],
) -> tuple[str, ...]:
    parts: list[str] = []
    for key in confidence_facts.signal_keys:
        if key == "raw_backed":
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_SIGNAL_RAW_BACKED",
                    samples=str(max(0, confidence_facts.raw_backed_sample_count)),
                )
            )
        elif key == "repeated_support":
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_SIGNAL_REPEATED_SUPPORT",
                    count=str(max(0, confidence_facts.supporting_window_count or 0)),
                )
            )
        elif key == "sustained_support" and confidence_facts.supporting_duration_s is not None:
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_SIGNAL_SUSTAINED_SUPPORT",
                    duration=f"{confidence_facts.supporting_duration_s:.1f}",
                )
            )
        elif key == "stable_frequency":
            low = confidence_facts.stable_frequency_min_hz
            high = confidence_facts.stable_frequency_max_hz
            if low is None or high is None:
                continue
            if abs(high - low) < 0.05:
                parts.append(
                    tr(
                        "REPORT_CONFIDENCE_SIGNAL_STABLE_FREQUENCY_SINGLE",
                        hz=f"{low:.1f}",
                    )
                )
            else:
                parts.append(
                    tr(
                        "REPORT_CONFIDENCE_SIGNAL_STABLE_FREQUENCY_BAND",
                        low=f"{low:.1f}",
                        high=f"{high:.1f}",
                    )
                )
        elif key == "tight_order_lock":
            parts.append(tr("REPORT_CONFIDENCE_SIGNAL_TIGHT_ORDER_LOCK"))
        elif key == "localized_support" and confidence_facts.top_support_location is not None:
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_SIGNAL_LOCALIZED_SUPPORT",
                    location=display_location(confidence_facts.top_support_location, tr=tr),
                )
            )
        elif key == "clean_signal":
            parts.append(tr("REPORT_CONFIDENCE_SIGNAL_CLEAN_SIGNAL"))
        elif key == "user_confirmed_vehicle_data":
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_SIGNAL_USER_CONFIRMED_VEHICLE_DATA",
                    scope=_vehicle_data_scope_text(confidence_facts, tr=tr),
                )
            )
    return tuple(parts)


def _confidence_caveat_texts(
    confidence_facts: ReportConfidenceFacts,
    *,
    tr: Callable[..., str],
) -> tuple[str, ...]:
    parts: list[str] = []
    for key in confidence_facts.caveat_keys:
        if key == "summary_only":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_SUMMARY_ONLY"))
        elif key == "raw_replay_incomplete":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_RAW_REPLAY_INCOMPLETE"))
        elif key == LEGACY_CONTEXT_CAVEAT_KEY:
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_LEGACY_CONTEXT"))
        elif key == "sparse_support":
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_CAVEAT_SPARSE_SUPPORT",
                    count=str(max(0, confidence_facts.supporting_window_count or 0)),
                )
            )
        elif key == "speed_context_gaps":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_SPEED_CONTEXT_GAPS"))
        elif key == "rpm_context_gaps":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_RPM_CONTEXT_GAPS"))
        elif key == "brief_support" and confidence_facts.supporting_duration_s is not None:
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_CAVEAT_BRIEF_SUPPORT",
                    duration=f"{confidence_facts.supporting_duration_s:.1f}",
                )
            )
        elif key == "drifting_frequency":
            low = confidence_facts.stable_frequency_min_hz
            high = confidence_facts.stable_frequency_max_hz
            if low is None or high is None:
                continue
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_CAVEAT_DRIFTING_FREQUENCY",
                    low=f"{low:.1f}",
                    high=f"{high:.1f}",
                )
            )
        elif key == "loose_order_lock":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_LOOSE_ORDER_LOCK"))
        elif key == "mixed_support_locations":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_MIXED_LOCATIONS"))
        elif key == "weak_spatial":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_WEAK_SPATIAL"))
        elif key == "close_alternative" and confidence_facts.alternative_source is not None:
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_CAVEAT_CLOSE_ALTERNATIVE",
                    source=human_source(confidence_facts.alternative_source, tr=tr),
                )
            )
        elif key == "incomplete_reference":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_REFERENCE_GAP"))
        elif key == "noisy_signal":
            parts.append(tr("REPORT_CONFIDENCE_CAVEAT_NOISY_SIGNAL"))
        elif key == "secondary_vehicle_data":
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_CAVEAT_SECONDARY_VEHICLE_DATA",
                    scope=_vehicle_data_scope_text(confidence_facts, tr=tr),
                )
            )
        elif key == "approximate_vehicle_data":
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_CAVEAT_APPROXIMATE_VEHICLE_DATA",
                    scope=_vehicle_data_scope_text(confidence_facts, tr=tr),
                )
            )
        elif key == "unverified_vehicle_data":
            parts.append(
                tr(
                    "REPORT_CONFIDENCE_CAVEAT_UNVERIFIED_VEHICLE_DATA",
                    scope=_vehicle_data_scope_text(confidence_facts, tr=tr),
                )
            )
    return tuple(parts)


def _vehicle_data_scope_text(
    confidence_facts: ReportConfidenceFacts,
    *,
    tr: Callable[..., str],
) -> str:
    if confidence_facts.car_data_reference_scope == "driveline":
        return tr("REPORT_CONFIDENCE_CAR_SCOPE_DRIVELINE")
    if confidence_facts.car_data_reference_scope == "engine_speed_derived":
        return tr("REPORT_CONFIDENCE_CAR_SCOPE_ENGINE_SPEED_DERIVED")
    return tr("REPORT_CONFIDENCE_CAR_SCOPE_TIRE")


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
        return ", ".join(finding.signature_labels[:2])
    if finding.order:
        return finding.order
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
