# ruff: noqa: E501
"""Test-plan merging and location/speed-bin summary helpers."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from .helpers import _speed_bin_label, _text
from .order_analysis import _finding_actions_for_source


def _merge_test_plan(
    findings: list[dict[str, object]],
    lang: object,
) -> list[dict[str, object]]:
    # Priority ordering: inspection/visual first, then balance/runout, then deeper
    ACTION_PRIORITY = {
        "wheel_tire_condition": 1,  # visual inspection – least invasive
        "wheel_balance_and_runout": 2,  # balance/runout check
        "engine_mounts_and_accessories": 3,
        "driveline_mounts_and_fasteners": 3,
        "driveline_inspection": 4,
        "engine_combustion_quality": 5,
        "general_mechanical_inspection": 6,
    }
    steps: list[dict[str, object]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_confidence = _as_float(finding.get("confidence_0_to_1"))
        finding_speed_band = str(finding.get("strongest_speed_band") or "").strip()
        finding_frequency = str(finding.get("frequency_hz_or_order") or "").strip()
        actions = finding.get("actions")
        if isinstance(actions, list) and actions:
            for step in actions:
                if not isinstance(step, dict):
                    continue
                enriched_step = dict(step)
                if finding_confidence is not None:
                    enriched_step.setdefault("certainty_0_to_1", f"{finding_confidence:.4f}")
                if finding_speed_band:
                    enriched_step.setdefault("speed_band", finding_speed_band)
                if finding_frequency:
                    enriched_step.setdefault("frequency_hz_or_order", finding_frequency)
                steps.append(enriched_step)
            continue
        source = str(finding.get("suspected_source") or "").strip().lower()
        generated_steps = _finding_actions_for_source(
            lang,
            source,
            strongest_location=str(finding.get("strongest_location") or ""),
            strongest_speed_band=str(finding.get("strongest_speed_band") or ""),
            weak_spatial_separation=bool(finding.get("weak_spatial_separation")),
        )
        for step in generated_steps:
            enriched_step = dict(step)
            if finding_confidence is not None:
                enriched_step.setdefault("certainty_0_to_1", f"{finding_confidence:.4f}")
            if finding_speed_band:
                enriched_step.setdefault("speed_band", finding_speed_band)
            if finding_frequency:
                enriched_step.setdefault("frequency_hz_or_order", finding_frequency)
            steps.append(enriched_step)

    dedup: dict[str, dict[str, object]] = {}
    ordered: list[dict[str, object]] = []
    for step in steps:
        action_id = str(step.get("action_id") or "").strip().lower()
        if not action_id:
            continue
        if action_id in dedup:
            continue
        dedup[action_id] = step
        ordered.append(step)

    # Sort by priority (least-invasive first), then preserve original order as tiebreak
    ordered.sort(
        key=lambda s: ACTION_PRIORITY.get(str(s.get("action_id") or "").strip().lower(), 99)
    )

    if ordered:
        return ordered[:5]
    return [
        {
            "action_id": "general_mechanical_inspection",
            "what": _tr(lang, "COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS"),
            "why": _tr(lang, "NO_ACTIONABLE_FINDINGS_WERE_GENERATED_FROM_CURRENT_DATA"),
            "confirm": _text(
                lang,
                "A concrete mechanical issue is identified.",
                "Een concrete mechanische afwijking wordt vastgesteld.",
            ),
            "falsify": _text(
                lang,
                "No abnormal play, wear, or looseness is detected.",
                "Er wordt geen abnormale speling, slijtage of losheid gedetecteerd.",
            ),
            "eta": "20-35 min",
        }
    ]


def _location_speedbin_summary(
    matches: list[dict[str, object]],
    lang: object,
) -> tuple[str, dict[str, object] | None]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in matches:
        speed = _as_float(row.get("speed_kmh"))
        amp = _as_float(row.get("amp"))
        location = str(row.get("location") or "").strip()
        if speed is None or speed <= 0 or amp is None or amp <= 0 or not location:
            continue
        grouped[_speed_bin_label(speed)][location].append(amp)

    if not grouped:
        return "", None

    best: dict[str, object] | None = None
    for bin_label, per_loc in grouped.items():
        ranked = sorted(
            ((loc, mean(vals)) for loc, vals in per_loc.items() if vals),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked:
            continue
        top_loc, top_amp = ranked[0]
        second_amp = ranked[1][1] if len(ranked) > 1 else top_amp
        dominance = (top_amp / second_amp) if second_amp > 0 else 1.0
        candidate = {
            "speed_range": bin_label,
            "location": top_loc,
            "mean_amp": top_amp,
            "dominance_ratio": dominance,
            "location_count": len(ranked),
            "weak_spatial_separation": dominance < 1.2,
        }
        if best is None or float(candidate["mean_amp"]) > float(best["mean_amp"]):
            best = candidate

    if best is None:
        return "", None

    sentence = _text(
        lang,
        (
            "Strongest at {location} in {speed_range} "
            "(~{dominance:.2f}x vs next location in that speed bin{weak_note})."
        ),
        (
            "Sterkst bij {location} in {speed_range} "
            "(~{dominance:.2f}x t.o.v. volgende locatie in die snelheidsband{weak_note})."
        ),
    ).format(
        location=best["location"],
        speed_range=best["speed_range"],
        dominance=float(best["dominance_ratio"]),
        weak_note=(
            _text(lang, ", weak spatial separation", ", zwakke ruimtelijke scheiding")
            if bool(best.get("weak_spatial_separation"))
            else ""
        ),
    )
    return sentence, best
