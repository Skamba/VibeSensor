"""Builder that converts an analysis summary dict into ReportTemplateData.

This module lives in ``vibesensor.analysis`` because it calls analysis
functions (certainty tiers, strength labels, pattern-parts mapping).
The sibling ``vibesensor.report`` package is renderer-only and imports
only the finished :class:`ReportTemplateData` dataclass.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import mean as _mean

from vibesensor_core.vibration_strength import vibration_strength_db_scalar

from .. import __version__
from ..report.i18n import normalize_lang
from ..report.i18n import tr as _tr
from ..report.report_data import (
    CarMeta,
    DataTrustItem,
    NextStep,
    ObservedSignature,
    PartSuggestion,
    PatternEvidence,
    PeakRow,
    ReportTemplateData,
    SystemFindingCard,
)
from ..runlog import as_float_or_none as _as_float
from .pattern_parts import parts_for_pattern, why_parts_listed
from .strength_labels import certainty_label, certainty_tier, strength_label, strength_text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human_source(source: object, *, tr) -> str:  # type: ignore[type-arg]
    raw = str(source or "").strip().lower()
    mapping = {
        "wheel/tire": tr("SOURCE_WHEEL_TIRE"),
        "driveline": tr("SOURCE_DRIVELINE"),
        "engine": tr("SOURCE_ENGINE"),
        "body resonance": tr("SOURCE_BODY_RESONANCE"),
        "unknown": tr("UNKNOWN"),
    }
    return mapping.get(raw, raw.replace("_", " ").title() if raw else tr("UNKNOWN"))


def _finding_strength_values(finding: dict) -> tuple[float | None, float | None]:
    amp_metric = finding.get("amplitude_metric")
    peak_amp_g = _as_float(amp_metric.get("value")) if isinstance(amp_metric, dict) else None

    evidence_metrics = finding.get("evidence_metrics")
    db_value = (
        _as_float(evidence_metrics.get("vibration_strength_db"))
        if isinstance(evidence_metrics, dict)
        else None
    )
    if db_value is not None:
        return (db_value, peak_amp_g)

    if isinstance(evidence_metrics, dict):
        noise_floor = _as_float(evidence_metrics.get("mean_noise_floor"))
        if peak_amp_g is not None and noise_floor is not None and noise_floor > 0:
            return (
                vibration_strength_db_scalar(
                    peak_band_rms_amp_g=peak_amp_g, floor_amp_g=noise_floor
                ),
                peak_amp_g,
            )

    return (None, peak_amp_g)


def _top_strength_values(summary: dict) -> tuple[float | None, float | None]:
    """Return best ``(vibration_strength_db, peak_amp_g)`` for observed strength text."""
    db_value: float | None = None
    peak_amp_g: float | None = None
    for cause in summary.get("top_causes", []):
        if not isinstance(cause, dict):
            continue
        for finding in summary.get("findings", []):
            if not isinstance(finding, dict):
                continue
            if finding.get("finding_id") != cause.get("finding_id"):
                continue
            finding_db, finding_peak = _finding_strength_values(finding)
            if finding_db is not None:
                return (finding_db, finding_peak)
            if peak_amp_g is None and finding_peak is not None:
                peak_amp_g = finding_peak

    sensor_rows = [
        _as_float(row.get("p95_intensity_db"))
        for row in summary.get("sensor_intensity_by_location", [])
        if isinstance(row, dict)
    ]
    sensor_db = max((value for value in sensor_rows if value is not None), default=None)
    if db_value is None and sensor_db is not None:
        db_value = sensor_db
    return (db_value, peak_amp_g)


def _dominant_phase(phase_info: dict | None) -> str | None:
    """Return the dominant non-idle driving phase from a phase_info summary dict."""
    if not isinstance(phase_info, dict):
        return None
    counts = phase_info.get("phase_counts")
    if not isinstance(counts, dict) or not counts:
        return None
    # Prefer the non-idle phase with the highest sample count.
    _IDLE_KEY = "idle"
    best_phase: str | None = None
    best_count = 0
    for phase_key, count in counts.items():
        if phase_key == _IDLE_KEY:
            continue
        if isinstance(count, (int, float)) and count > best_count:
            best_count = int(count)
            best_phase = phase_key
    return best_phase


def _peak_classification_text(value: object, tr: Callable[..., str] | None = None) -> str:
    normalized = str(value or "").strip().lower()
    if tr is not None:
        if normalized == "patterned":
            return tr("CLASSIFICATION_PATTERNED")
        if normalized == "persistent":
            return tr("CLASSIFICATION_PERSISTENT")
        if normalized == "transient":
            return tr("CLASSIFICATION_TRANSIENT")
        if normalized == "baseline_noise":
            return tr("CLASSIFICATION_BASELINE_NOISE")
        return tr("CLASSIFICATION_PERSISTENT")
    # Fallback without translator (backward compat)
    if normalized == "patterned":
        return "patterned"
    if normalized == "persistent":
        return "persistent"
    if normalized == "transient":
        return "transient impact"
    if normalized == "baseline_noise":
        return "noise floor"
    return "persistent"


def _has_relevant_reference_gap(findings: list[dict], primary_source: object) -> bool:
    src = str(primary_source or "").strip().lower()
    for finding in findings:
        fid = str(finding.get("finding_id") or "").strip().upper()
        if fid in {"REF_SPEED", "REF_SAMPLE_RATE"}:
            return True
        if fid == "REF_WHEEL" and src in {"wheel/tire", "driveline"}:
            return True
        if fid == "REF_ENGINE" and src == "engine":
            return True
    return False


def _compute_location_hotspot_rows(
    findings: list[dict],
    sensor_intensity: list[dict],
) -> list[dict]:
    """Pre-compute location hotspot rows from findings matched_points.

    Falls back to sensor_intensity_by_location when no matched_points
    are available.  Never reads raw time-series samples.
    """
    amp_by_location: dict[str, list[float]] = defaultdict(list)

    # Prefer matched_points from findings (amplitude in g).
    matched_points: list[dict] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        rows = finding.get("matched_points")
        if isinstance(rows, list) and rows:
            matched_points = [r for r in rows if isinstance(r, dict)]
            break

    if matched_points:
        for row in matched_points:
            location = str(row.get("location") or "").strip()
            amp = _as_float(row.get("amp"))
            if location and amp is not None and amp > 0:
                amp_by_location[location].append(amp)
        amp_unit = "g"
    elif sensor_intensity:
        for row in sensor_intensity:
            if not isinstance(row, dict):
                continue
            location = str(row.get("location") or "").strip()
            p95 = _as_float(row.get("p95_intensity_db")) or _as_float(
                row.get("mean_intensity_db")
            )
            if location and p95 is not None and p95 > 0:
                amp_by_location[location].append(p95)
        amp_unit = "db"
    else:
        return []

    hotspot_rows: list[dict] = []
    for location, amps in amp_by_location.items():
        peak_val = max(amps)
        mean_val = _mean(amps)
        row: dict = {
            "location": location,
            "count": len(amps),
            "unit": amp_unit,
            "peak_value": peak_val,
            "mean_value": mean_val,
        }
        if amp_unit == "g":
            row["peak_g"] = peak_val
            row["mean_g"] = mean_val
        else:
            row["peak_db"] = peak_val
            row["mean_db"] = mean_val
        hotspot_rows.append(row)
    hotspot_rows.sort(
        key=lambda r: (float(r["peak_value"]), float(r["mean_value"])),
        reverse=True,
    )
    return hotspot_rows


# ---------------------------------------------------------------------------
# Summary → template data mapper
# ---------------------------------------------------------------------------


def map_summary(summary: dict) -> ReportTemplateData:
    """Map a run summary dict to the report template data model."""
    lang = normalize_lang(summary.get("lang"))

    def tr(key: str, **kw: object) -> str:
        return _tr(lang, key, **kw)

    # -- Metadata --
    meta = summary.get("metadata", {}) if isinstance(summary.get("metadata"), dict) else {}
    car_name = str(meta.get("car_name") or meta.get("vehicle_name") or "").strip() or None
    car_type = str(meta.get("car_type") or meta.get("vehicle_type") or "").strip() or None

    # -- Date --
    report_date = summary.get("report_date") or datetime.now(UTC).isoformat()
    date_str = str(report_date)[:19].replace("T", " ")

    # -- Top causes and findings --
    findings = [f for f in summary.get("findings", []) if isinstance(f, dict)]
    findings_non_ref = [
        f for f in findings if not str(f.get("finding_id") or "").strip().upper().startswith("REF_")
    ]
    top_causes_all = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]
    top_causes_non_ref = [
        c
        for c in top_causes_all
        if not str(c.get("finding_id") or "").strip().upper().startswith("REF_")
    ]
    top_causes_actionable = [
        c
        for c in top_causes_non_ref
        if str(c.get("source") or c.get("suspected_source") or "").strip().lower()
        not in {"unknown_resonance", "unknown"}
        or str(c.get("strongest_location") or "").strip().lower()
        not in {"", "unknown", "not available", "n/a"}
    ]
    top_causes = top_causes_actionable or findings_non_ref or top_causes_non_ref or top_causes_all
    speed_stats = (
        summary.get("speed_stats", {}) if isinstance(summary.get("speed_stats"), dict) else {}
    )
    origin = summary.get("most_likely_origin", {})
    if not isinstance(origin, dict):
        origin = {}
    origin_location = str(origin.get("location") or "").strip()

    # -- Phase info --
    raw_phase_info = summary.get("phase_info")
    phase_info = dict(raw_phase_info) if isinstance(raw_phase_info, dict) else None
    dom_phase = _dominant_phase(phase_info)

    # -- Observed signature --
    primary_candidates = top_causes or findings_non_ref
    primary_candidate = primary_candidates[0] if primary_candidates else None
    if primary_candidate:
        primary_source = primary_candidate.get("source") or primary_candidate.get(
            "suspected_source"
        )
        primary_system = _human_source(primary_source, tr=tr)
        primary_location = origin_location or str(
            primary_candidate.get("strongest_location") or tr("UNKNOWN")
        )
        primary_speed = str(
            primary_candidate.get("strongest_speed_band")
            or primary_candidate.get("speed_band")
            or primary_candidate.get("dominant_speed_band")
            or tr("UNKNOWN")
        )
        _conf_val = _as_float(primary_candidate.get("confidence"))
        if _conf_val is None:
            _conf_val = _as_float(primary_candidate.get("confidence_0_to_1"))
        conf = _conf_val if _conf_val is not None else 0.0
    else:
        primary_source = None
        primary_system = tr("UNKNOWN")
        primary_location = origin_location or tr("UNKNOWN")
        primary_speed = tr("UNKNOWN")
        conf = 0.0

    db_val, peak_amp_g = _top_strength_values(summary)
    str_text = strength_text(db_val, lang=lang, peak_amp_g=peak_amp_g)

    steady = bool(speed_stats.get("steady_speed"))
    weak_spatial = bool(
        primary_candidate.get("weak_spatial_separation") if primary_candidate else False
    )
    sensor_count = int(_as_float(summary.get("sensor_count_used")) or 0)
    has_ref_gaps = _has_relevant_reference_gap(findings, primary_source)

    cert_key, cert_label_text, cert_pct, cert_reason = certainty_label(
        conf,
        lang=lang,
        steady_speed=steady,
        weak_spatial=weak_spatial,
        sensor_count=sensor_count,
        has_reference_gaps=has_ref_gaps,
        strength_band_key=strength_label(db_val)[0] if db_val is not None else None,
    )

    tier = certainty_tier(conf)

    observed = ObservedSignature(
        primary_system=primary_system,
        strongest_sensor_location=primary_location,
        speed_band=primary_speed,
        phase=dom_phase,
        strength_label=str_text,
        strength_peak_amp_g=peak_amp_g,
        certainty_label=cert_label_text,
        certainty_pct=cert_pct,
        certainty_reason=cert_reason,
    )

    # -- System cards --
    system_cards: list[SystemFindingCard] = []
    if tier == "A":
        # Tier A: suppress specific system findings entirely.
        pass
    else:
        card_sources = top_causes or findings_non_ref or findings
        for cause in card_sources[:3]:
            src = cause.get("source") or cause.get("suspected_source") or "unknown"
            src_human = _human_source(src, tr=tr)
            location = str(cause.get("strongest_location") or tr("UNKNOWN"))
            sigs = cause.get("signatures_observed", [])
            pattern_text = ", ".join(str(s) for s in sigs[:3]) if sigs else tr("UNKNOWN")
            order_label = str(sigs[0]) if sigs else None
            parts_list = parts_for_pattern(str(src), order_label, lang=lang)
            _c_conf_val = _as_float(cause.get("confidence"))
            if _c_conf_val is None:
                _c_conf_val = _as_float(cause.get("confidence_0_to_1"))
            c_conf = _c_conf_val if _c_conf_val is not None else 0.0
            _ck, _cl, _cp, c_reason = certainty_label(c_conf, lang=lang)
            tone = cause.get("confidence_tone", "neutral")

            card_system_name = src_human
            card_parts = [PartSuggestion(name=p, why_shown=c_reason) for p in parts_list]
            if tier == "B":
                # Tier B: label as hypothesis, suppress repair-oriented parts.
                card_system_name = f"{src_human} — {tr('TIER_B_HYPOTHESIS_LABEL')}"
                card_parts = []

            system_cards.append(
                SystemFindingCard(
                    system_name=card_system_name,
                    strongest_location=location,
                    pattern_summary=pattern_text,
                    parts=card_parts,
                    tone=tone,
                )
            )

    # -- Next steps --
    next_steps: list[NextStep] = []
    if tier == "A":
        # Tier A: replace repair steps with data-collection guidance.
        _guidance = [
            (tr("TIER_A_CAPTURE_WIDER_SPEED"), cert_reason),
            (tr("TIER_A_CAPTURE_MORE_SENSORS"), cert_reason),
            (tr("TIER_A_CAPTURE_REFERENCE_DATA"), cert_reason),
        ]
        for idx, (action, why) in enumerate(_guidance, start=1):
            next_steps.append(NextStep(action=action, why=why, rank=idx))
    else:
        test_plan = [s for s in summary.get("test_plan", []) if isinstance(s, dict)]
        for idx, step in enumerate(test_plan, start=1):
            what = str(step.get("what") or "")
            why = str(step.get("why") or "")
            next_steps.append(
                NextStep(
                    action=what,
                    why=why or None,
                    rank=idx,
                    speed_band=str(step.get("speed_band") or "") or None,
                    confirm=str(step.get("confirm") or "") or None,
                    falsify=str(step.get("falsify") or "") or None,
                    eta=str(step.get("eta") or "") or None,
                )
            )

    # -- Data trust --
    data_trust: list[DataTrustItem] = []
    for item in summary.get("run_suitability", []):
        if isinstance(item, dict):
            check_raw = str(item.get("check") or "")
            check_text = tr(check_raw) if check_raw.startswith("SUITABILITY_CHECK_") else check_raw
            detail = str(item.get("explanation") or "").strip() or None
            data_trust.append(
                DataTrustItem(
                    check=check_text,
                    state=str(item.get("state") or "warn"),
                    detail=detail,
                )
            )

    # -- Pattern evidence --
    systems = [
        _human_source(c.get("source") or c.get("suspected_source"), tr=tr) for c in top_causes[:3]
    ]
    pe_loc = primary_location
    pe_speed = primary_speed
    interp = str(origin.get("explanation", "")) if isinstance(origin, dict) else ""
    src_why = str(
        (primary_candidate.get("source") or primary_candidate.get("suspected_source"))
        if primary_candidate
        else ""
    )
    sigs_why = primary_candidate.get("signatures_observed", []) if primary_candidate else []
    order_lbl_why = str(sigs_why[0]) if sigs_why else None
    why_text = why_parts_listed(src_why, order_lbl_why, lang=lang)

    warning_text = cert_reason if weak_spatial else None

    pattern_evidence = PatternEvidence(
        matched_systems=systems,
        strongest_location=pe_loc,
        speed_band=pe_speed,
        strength_label=str_text,
        strength_peak_amp_g=peak_amp_g,
        certainty_label=cert_label_text,
        certainty_pct=cert_pct,
        certainty_reason=cert_reason,
        warning=warning_text,
        interpretation=interp or None,
        why_parts_text=why_text,
    )

    # -- Peak rows --
    plots = summary.get("plots", {}) if isinstance(summary.get("plots"), dict) else {}
    peak_rows: list[PeakRow] = []
    for row in (plots.get("peaks_table", []) or [])[:8]:
        if not isinstance(row, dict):
            continue
        rank_val = _as_float(row.get("rank"))
        rank = str(int(rank_val)) if rank_val is not None else "\u2014"
        freq_val = _as_float(row.get("frequency_hz"))
        freq = f"{freq_val:.1f}" if freq_val is not None else "\u2014"
        classification = _peak_classification_text(row.get("peak_classification"), tr=tr)
        order_label = str(row.get("order_label") or "").strip()
        order = order_label or classification
        amp_val = _as_float(row.get("p95_amp_g"))
        amp = f"{amp_val:.4f}" if amp_val is not None else "\u2014"
        strength_db_val = _as_float(row.get("strength_db"))
        strength_db = f"{strength_db_val:.1f}" if strength_db_val is not None else "\u2014"
        speed = str(row.get("typical_speed_band") or "\u2014")
        presence = float(_as_float(row.get("presence_ratio")) or 0.0)
        score = float(_as_float(row.get("persistence_score")) or 0.0)

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
            system = "\u2014"
        relevance = (
            f"{classification} \u00b7 {presence:.0%} "
            f"{tr('PRESENCE')} \u00b7 {tr('SCORE')} {score:.2f}"
        )

        peak_rows.append(
            PeakRow(
                rank=rank,
                system=system,
                freq_hz=freq,
                order=order,
                amp_g=amp,
                strength_db=strength_db,
                speed_band=speed,
                relevance=relevance,
            )
        )

    # -- Version marker --
    git_sha = str(os.getenv("GIT_SHA", "")).strip()
    version_marker = f"v{__version__} ({git_sha[:8]})" if git_sha else f"v{__version__}"

    # -- Metadata enrichment --
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

    sample_count = int(_as_float(summary.get("rows")) or 0)
    sensor_locations_list = summary.get("sensor_locations", [])
    if not isinstance(sensor_locations_list, list):
        sensor_locations_list = []
    sensor_count_used = int(_as_float(summary.get("sensor_count_used")) or 0)
    sensor_model_val = str(summary.get("sensor_model") or "").strip() or None
    firmware_version_val = str(summary.get("firmware_version") or "").strip() or None

    # -- Rendering context (pre-computed for the PDF renderer) --
    raw_findings = [f for f in summary.get("findings", []) if isinstance(f, dict)]
    raw_sensor_intensity = summary.get("sensor_intensity_by_location", [])
    if not isinstance(raw_sensor_intensity, list):
        raw_sensor_intensity = []

    # Pre-compute location hotspot rows from findings matched_points
    # so the PDF renderer never reads raw samples.
    hotspot_rows = _compute_location_hotspot_rows(raw_findings, raw_sensor_intensity)

    return ReportTemplateData(
        title=tr("DIAGNOSTIC_WORKSHEET"),
        run_datetime=date_str,
        run_id=summary.get("run_id"),
        duration_text=duration_text,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
        sample_rate_hz=sample_rate_hz,
        tire_spec_text=tire_spec_text,
        sample_count=sample_count,
        sensor_count=sensor_count_used,
        sensor_locations=[str(loc) for loc in sensor_locations_list],
        sensor_model=sensor_model_val,
        firmware_version=firmware_version_val,
        car=CarMeta(name=car_name, car_type=car_type),
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        phase_info=phase_info,
        version_marker=version_marker,
        lang=lang,
        certainty_tier_key=tier,
        findings=raw_findings,
        top_causes=top_causes,
        sensor_intensity_by_location=raw_sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
