# ruff: noqa: E501
"""Test-plan merging and location/speed-bin summary helpers."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from ..constants import WEAK_SPATIAL_DOMINANCE_THRESHOLD
from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from .helpers import _speed_bin_label
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
            "confirm": _tr(
                lang,
                "CONFIRM_CONCRETE_MECHANICAL_ISSUE_IDENTIFIED",
            ),
            "falsify": _tr(
                lang,
                "FALSIFY_NO_ABNORMAL_PLAY_WEAR_OR_LOOSENESS",
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

    per_bin_results: list[dict[str, object]] = []
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
            "weak_spatial_separation": dominance < WEAK_SPATIAL_DOMINANCE_THRESHOLD,
        }
        per_bin_results.append(candidate)
        if best is None or float(candidate["mean_amp"]) > float(best["mean_amp"]):
            best = candidate

    if best is None:
        return "", None

    # Attach per-bin breakdown so callers can inspect per-speed-bin location
    # rankings instead of only getting the global winner.
    # Use detached copies to avoid self-referential structures when `best`
    # points to one of the dicts in `per_bin_results`.
    best_out = dict(best)
    best_out["per_bin_results"] = [dict(item) for item in per_bin_results]

    sentence = _tr(
        lang,
        "STRONGEST_AT_LOCATION_IN_SPEED_RANGE",
        location=best_out["location"],
        speed_range=best_out["speed_range"],
        dominance=f"{float(best_out['dominance_ratio']):.2f}",
        weak_note=(
            _tr(lang, "WEAK_SPATIAL_SEPARATION_NOTE")
            if bool(best_out.get("weak_spatial_separation"))
            else ""
        ),
    )
    return sentence, best_out
