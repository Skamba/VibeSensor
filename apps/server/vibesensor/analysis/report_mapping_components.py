"""Component builders for mapping analysis summaries to report data."""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from statistics import mean as _mean

from .. import __version__
from ..report.report_data import (
    DataTrustItem,
    NextStep,
    PartSuggestion,
    PatternEvidence,
    PeakRow,
    SystemFindingCard,
)
from ..runlog import as_float_or_none as _as_float
from .pattern_parts import parts_for_pattern, why_parts_listed
from .report_mapping_common import (
    finding_strength_db,
    human_source,
    is_i18n_ref,
    order_label_human,
    peak_classification_text,
    resolve_i18n,
)


def top_strength_values(
    summary: dict,
    *,
    effective_causes: list[dict] | None = None,
) -> float | None:
    """Return the best available vibration strength in dB for report text."""
    causes = effective_causes if effective_causes is not None else summary.get("top_causes", [])
    all_findings = summary.get("findings", [])
    for cause in causes:
        if not isinstance(cause, dict):
            continue
        for finding in all_findings:
            if not isinstance(finding, dict):
                continue
            if finding.get("finding_id") != cause.get("finding_id"):
                continue
            finding_db = finding_strength_db(finding)
            if finding_db is not None:
                return finding_db

    sensor_rows = [
        _as_float(row.get("p95_intensity_db"))
        for row in summary.get("sensor_intensity_by_location", [])
        if isinstance(row, dict)
    ]
    return max((value for value in sensor_rows if value is not None), default=None)


def has_relevant_reference_gap(findings: list[dict], primary_source: object) -> bool:
    """Whether the report certainty should mention missing reference inputs."""
    source = str(primary_source or "").strip().lower()
    for finding in findings:
        finding_id = str(finding.get("finding_id") or "").strip().upper()
        if finding_id in {"REF_SPEED", "REF_SAMPLE_RATE"}:
            return True
        if finding_id == "REF_WHEEL" and source in {"wheel/tire", "driveline"}:
            return True
        if finding_id == "REF_ENGINE" and source == "engine":
            return True
    return False


def build_next_steps_from_summary(
    summary: dict,
    *,
    tier: str,
    cert_reason: str,
    lang: str,
    tr: Callable,
) -> list[NextStep]:
    """Build next-step actions from a run summary dict."""
    next_steps: list[NextStep] = []
    if tier == "A":
        guidance = [
            (tr("TIER_A_CAPTURE_WIDER_SPEED"), cert_reason),
            (tr("TIER_A_CAPTURE_MORE_SENSORS"), cert_reason),
            (tr("TIER_A_CAPTURE_REFERENCE_DATA"), cert_reason),
        ]
        for action, why in guidance:
            next_steps.append(NextStep(action=action, why=why))
        return next_steps

    test_plan = [step for step in summary.get("test_plan", []) if isinstance(step, dict)]
    for step in test_plan:
        what_raw = step.get("what") or ""
        why_raw = step.get("why") or ""
        confirm_raw = step.get("confirm") or ""
        falsify_raw = step.get("falsify") or ""
        next_steps.append(
            NextStep(
                action=(
                    resolve_i18n(lang, what_raw, tr=tr) if is_i18n_ref(what_raw) else str(what_raw)
                ),
                why=(resolve_i18n(lang, why_raw, tr=tr) if is_i18n_ref(why_raw) else str(why_raw))
                or None,
                confirm=(
                    resolve_i18n(lang, confirm_raw, tr=tr)
                    if is_i18n_ref(confirm_raw)
                    else str(confirm_raw)
                )
                or None,
                falsify=(
                    resolve_i18n(lang, falsify_raw, tr=tr)
                    if is_i18n_ref(falsify_raw)
                    else str(falsify_raw)
                )
                or None,
                eta=str(step.get("eta") or "") or None,
            )
        )
    return next_steps


def build_data_trust_from_summary(
    summary: dict,
    *,
    lang: str,
    tr: Callable,
) -> list[DataTrustItem]:
    """Build the data-trust checklist from run_suitability items."""
    data_trust: list[DataTrustItem] = []
    for item in summary.get("run_suitability", []):
        if not isinstance(item, dict):
            continue
        check_raw = item.get("check") or ""
        if is_i18n_ref(check_raw):
            check_text = resolve_i18n(lang, check_raw, tr=tr)
        elif isinstance(check_raw, str) and check_raw.startswith("SUITABILITY_CHECK_"):
            check_text = tr(check_raw)
        else:
            check_text = str(check_raw)
        explanation_raw = item.get("explanation") or ""
        detail = (
            resolve_i18n(lang, explanation_raw, tr=tr).strip()
            if is_i18n_ref(explanation_raw) or isinstance(explanation_raw, list)
            else (str(explanation_raw).strip() or None)
        )
        data_trust.append(
            DataTrustItem(
                check=check_text,
                state=str(item.get("state") or "warn"),
                detail=detail,
            )
        )
    return data_trust


def build_peak_rows_from_plots(
    summary: dict,
    *,
    lang: str,
    tr: Callable,
) -> list[PeakRow]:
    """Build peak-table rows from the plots section."""
    plots = summary.get("plots")
    if not isinstance(plots, dict):
        plots = {}
    peak_rows: list[PeakRow] = []
    raw_peaks = [row for row in (plots.get("peaks_table", []) or []) if isinstance(row, dict)]
    above_noise = [
        row
        for row in raw_peaks
        if ((_sdb := _as_float(row.get("strength_db"))) is None or _sdb > 0)
    ]
    for row in above_noise[:8]:
        rank_val = _as_float(row.get("rank"))
        rank = str(int(rank_val)) if rank_val is not None else "—"
        freq_val = _as_float(row.get("frequency_hz"))
        freq = f"{freq_val:.1f}" if freq_val is not None else "—"
        classification = peak_classification_text(row.get("peak_classification"), tr=tr)
        order_label_raw = str(row.get("order_label") or "").strip()
        order = order_label_human(lang, order_label_raw) if order_label_raw else classification
        peak_db_val = _as_float(row.get("p95_intensity_db"))
        peak_db = f"{peak_db_val:.1f}" if peak_db_val is not None else "—"
        strength_db_val = _as_float(row.get("strength_db"))
        strength_db = f"{strength_db_val:.1f}" if strength_db_val is not None else "—"
        speed = str(row.get("typical_speed_band") or "—")
        presence = _as_float(row.get("presence_ratio")) or 0.0
        score = _as_float(row.get("persistence_score")) or 0.0

        order_lower = order.lower()
        source_hint = str(row.get("source") or row.get("suspected_source") or "").strip().lower()
        if (source_hint == "wheel/tire") or ("wheel" in order_lower):
            system = tr("SOURCE_WHEEL_TIRE")
        elif (source_hint == "engine") or ("engine" in order_lower):
            system = tr("SOURCE_ENGINE")
        elif (
            (source_hint == "driveline")
            or ("driveshaft" in order_lower)
            or ("drive" in order_lower)
        ):
            system = tr("SOURCE_DRIVELINE")
        elif "transient" in order_lower:
            system = tr("SOURCE_TRANSIENT_IMPACT")
        else:
            system = "—"
        relevance = (
            f"{classification} · {presence:.0%} {tr('PRESENCE')} · {tr('SCORE')} {score:.2f}"
        )
        peak_rows.append(
            PeakRow(
                rank=rank,
                system=system,
                freq_hz=freq,
                order=order,
                peak_db=peak_db,
                strength_db=strength_db,
                speed_band=speed,
                relevance=relevance,
            )
        )
    return peak_rows


def build_system_cards(
    top_causes: list[dict],
    findings_non_ref: list[dict],
    findings: list[dict],
    tier: str,
    lang: str,
    tr: Callable,
) -> list[SystemFindingCard]:
    """Build system finding cards for the report template."""
    if tier == "A":
        return []
    card_sources = top_causes or findings_non_ref or findings
    cards: list[SystemFindingCard] = []
    for cause in card_sources[:2]:
        source = cause.get("source") or cause.get("suspected_source") or "unknown"
        source_human = human_source(source, tr=tr)
        location = str(cause.get("strongest_location") or tr("UNKNOWN"))
        signatures = cause.get("signatures_observed", [])
        signatures_human = (
            [order_label_human(lang, str(sig)) for sig in signatures[:3]] if signatures else []
        )
        pattern_text = ", ".join(signatures_human) if signatures_human else tr("UNKNOWN")
        order_label = signatures_human[0] if signatures_human else None
        parts_list = parts_for_pattern(str(source), order_label, lang=lang)

        card_system_name = source_human
        card_parts = [PartSuggestion(name=part) for part in parts_list]
        if tier == "B":
            card_system_name = f"{source_human} — {tr('TIER_B_HYPOTHESIS_LABEL')}"
            card_parts = []

        cards.append(
            SystemFindingCard(
                system_name=card_system_name,
                strongest_location=location,
                pattern_summary=pattern_text,
                parts=card_parts,
                tone=cause.get("confidence_tone", "neutral"),
            )
        )
    return cards


def build_pattern_evidence(
    top_causes: list[dict],
    primary_candidate: dict | None,
    origin: dict,
    primary_location: str,
    primary_speed: str,
    strength_text: str,
    db_val: float | None,
    cert_label_text: str,
    cert_pct: str,
    cert_reason: str,
    weak_spatial: bool,
    lang: str,
    tr: Callable,
) -> PatternEvidence:
    """Build the pattern-evidence block for the report template."""
    systems_raw = [
        human_source(cause.get("source") or cause.get("suspected_source"), tr=tr)
        for cause in top_causes[:3]
    ]
    systems = list(dict.fromkeys(systems_raw))
    interpretation_raw = origin.get("explanation", "") if isinstance(origin, dict) else ""
    interpretation = (
        resolve_i18n(lang, interpretation_raw, tr=tr)
        if is_i18n_ref(interpretation_raw) or isinstance(interpretation_raw, list)
        else str(interpretation_raw)
    )
    source_for_why = str(
        (primary_candidate.get("source") or primary_candidate.get("suspected_source"))
        if primary_candidate
        else ""
    )
    signatures_for_why = (
        primary_candidate.get("signatures_observed", []) if primary_candidate else []
    )
    order_label_for_why = (
        order_label_human(lang, str(signatures_for_why[0])) if signatures_for_why else None
    )
    return PatternEvidence(
        matched_systems=systems,
        strongest_location=primary_location,
        speed_band=primary_speed,
        strength_label=strength_text,
        strength_peak_db=db_val,
        certainty_label=cert_label_text,
        certainty_pct=cert_pct,
        certainty_reason=cert_reason,
        warning=cert_reason if weak_spatial else None,
        interpretation=interpretation or None,
        why_parts_text=why_parts_listed(source_for_why, order_label_for_why, lang=lang),
    )


def build_run_metadata_fields(summary: dict, meta: dict) -> dict[str, object]:
    """Extract and format run metadata text fields for the report template."""
    duration_text = str(summary.get("record_length") or "") or None
    start_time_utc = str(summary.get("start_time_utc") or "").strip() or None
    end_time_utc = str(summary.get("end_time_utc") or "").strip() or None
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    sample_rate_hz = f"{raw_sample_rate_hz:g}" if raw_sample_rate_hz is not None else None

    tire_width_mm = _as_float(meta.get("tire_width_mm"))
    tire_aspect_pct = _as_float(meta.get("tire_aspect_pct"))
    rim_in = _as_float(meta.get("rim_in"))
    tire_spec_text: str | None = None
    if (
        tire_width_mm is not None
        and tire_aspect_pct is not None
        and rim_in is not None
        and tire_width_mm > 0
        and tire_aspect_pct > 0
        and rim_in > 0
    ):
        tire_spec_text = f"{tire_width_mm:g}/{tire_aspect_pct:g}R{rim_in:g}"

    return {
        "duration_text": duration_text,
        "start_time_utc": start_time_utc,
        "end_time_utc": end_time_utc,
        "sample_rate_hz": sample_rate_hz,
        "tire_spec_text": tire_spec_text,
        "sample_count": int(_as_float(summary.get("rows")) or 0),
        "sensor_model": str(summary.get("sensor_model") or "").strip() or None,
        "firmware_version": str(summary.get("firmware_version") or "").strip() or None,
    }


def filter_active_sensor_intensity(
    raw_sensor_intensity_all: list,
    sensor_locations_active: list[str],
) -> list[dict]:
    """Filter sensor intensity rows to only active locations."""
    active_locations = set(sensor_locations_active)
    if active_locations:
        return [
            row
            for row in raw_sensor_intensity_all
            if isinstance(row, dict) and str(row.get("location") or "") in active_locations
        ]
    return [row for row in raw_sensor_intensity_all if isinstance(row, dict)]


def compute_location_hotspot_rows(sensor_intensity: list[dict]) -> list[dict]:
    """Pre-compute location hotspot rows from sensor intensity data."""
    if not sensor_intensity:
        return []

    amp_by_location: dict[str, list[float]] = defaultdict(list)
    for row in sensor_intensity:
        if not isinstance(row, dict):
            continue
        location = str(row.get("location") or "").strip()
        p95_val = _as_float(row.get("p95_intensity_db"))
        p95 = p95_val if p95_val is not None else _as_float(row.get("mean_intensity_db"))
        if location and p95 is not None and p95 > 0:
            amp_by_location[location].append(p95)

    hotspot_rows: list[dict] = []
    for location, amps in amp_by_location.items():
        hotspot_rows.append(
            {
                "location": location,
                "count": len(amps),
                "unit": "db",
                "peak_value": max(amps),
                "mean_value": _mean(amps),
            }
        )
    hotspot_rows.sort(
        key=lambda row: (float(row.get("peak_value") or 0.0), float(row.get("mean_value") or 0.0)),
        reverse=True,
    )
    return hotspot_rows


def build_version_marker() -> str:
    """Return the report version marker including the short git sha when present."""
    git_sha = str(os.getenv("GIT_SHA", "")).strip()
    return f"v{__version__} ({git_sha[:8]})" if git_sha else f"v{__version__}"
