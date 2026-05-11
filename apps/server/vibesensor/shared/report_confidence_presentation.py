"""Confidence and fallback wording for report presentation."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import Finding
from vibesensor.domain.diagnosis_assessment import LEGACY_CONTEXT_CAVEAT_KEY
from vibesensor.shared.boundaries.reporting.confidence_facts import ReportConfidenceFacts
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
from vibesensor.shared.report_presentation import display_location, human_source

__all__ = [
    "confidence_caveat_text",
    "confidence_pct_text",
    "confidence_reason_text",
    "confidence_snapshot_text",
    "first_confidence_reason_clause",
    "proof_caveat_text",
]


def first_confidence_reason_clause(primary_candidate_facts: PrimaryReportFacts) -> str | None:
    finding = primary_candidate_facts.domain_primary
    if finding is None or finding.confidence_assessment is None:
        return None
    for clause in str(finding.confidence_assessment.reason or "").split(";"):
        text = clause.strip().rstrip(".")
        if text:
            return text
    return None


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
        return _localized_fallback_reason(confidence_facts.fallback_reason, tr=tr) or (
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


def _localized_fallback_reason(value: object, *, tr: Callable[..., str]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _display_lang(tr) != "nl":
        return text
    replacements = {
        "missing reference data may affect accuracy": "Referentie ontbreekt",
        "speed was not steady during measurement": "snelheid wisselde",
    }
    clauses: list[str] = []
    for clause in text.split(";"):
        cleaned = clause.strip().rstrip(".")
        if not cleaned:
            continue
        clauses.append(replacements.get(cleaned.casefold(), cleaned))
    return "; ".join(clauses)


def _display_lang(tr: Callable[..., str]) -> str:
    try:
        return "nl" if tr("UNKNOWN") == "Onbekend" else "en"
    except Exception:
        return "en"
