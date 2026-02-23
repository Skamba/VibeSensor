# ruff: noqa: E501
"""Test-plan merging and location/speed-bin summary helpers."""

from __future__ import annotations

from collections import defaultdict
from math import ceil, floor, log1p, pow
from statistics import mean

from ..diagnostics_shared import MULTI_SENSOR_CORROBORATION_DB
from ..locations import is_wheel_location
from ..runlog import as_float_or_none as _as_float
from .helpers import _speed_bin_label, weak_spatial_dominance_threshold
from .i18n import tr as _tr
from .order_analysis import _finding_actions_for_source

NEAR_TIE_DOMINANCE_THRESHOLD = 1.15


def _weighted_percentile_speed(
    speed_weight_pairs: list[tuple[float, float]],
    percentile_0_to_1: float,
) -> float | None:
    valid = [(speed, weight) for speed, weight in speed_weight_pairs if speed > 0 and weight > 0]
    if not valid:
        return None
    ordered = sorted(valid, key=lambda item: item[0])
    total_weight = sum(weight for _, weight in ordered)
    if total_weight <= 0:
        return None
    target = max(0.0, min(1.0, percentile_0_to_1)) * total_weight
    cumulative = 0.0
    for speed, weight in ordered:
        cumulative += weight
        if cumulative >= target:
            return speed
    return ordered[-1][0]


def _weighted_speed_window_label(speed_weight_pairs: list[tuple[float, float]]) -> str | None:
    p10 = _weighted_percentile_speed(speed_weight_pairs, 0.10)
    p90 = _weighted_percentile_speed(speed_weight_pairs, 0.90)
    if p10 is None or p90 is None:
        return None
    low = int(floor(min(p10, p90)))
    high = int(ceil(max(p10, p90)))
    if high < low:
        high = low
    return f"{low}-{high} km/h"


def _localization_confidence(
    *,
    dominance_ratio: float,
    location_count: int,
    total_samples: int,
) -> float:
    dominance_component = max(0.0, min(1.0, (dominance_ratio - 1.0) / 0.5))
    location_component = 1.0 / max(1.0, 1.0 + (max(0, location_count - 1) * 0.15))
    sample_component = min(1.0, max(0.0, total_samples / 10.0))
    confidence = dominance_component * location_component * (0.6 + 0.4 * sample_component)
    return max(0.05, min(1.0, confidence))


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
    relevant_speed_bins: list[str] | tuple[str, ...] | set[str] | None = None,
    connected_locations: set[str] | None = None,
    suspected_source: str | None = None,
) -> tuple[str, dict[str, object] | None]:
    """Return strongest location summary, optionally restricted to specific speed bins.

    When ``relevant_speed_bins`` is provided, location ranking is computed only
    from samples that fall inside those speed-bin labels (for example
    ``{"90-100 km/h"}``). This allows order findings to localize the strongest
    sensor in the same speed range where the order is most relevant.

    When ``suspected_source`` is ``"wheel/tire"``, eligible wheel/corner
    locations are preferred as fault sources.  Non-wheel sensors may appear
    as transfer-path evidence but will not be selected as the strongest
    location unless no wheel sensors are present.
    """
    allowed_bins = {
        str(bin_label).strip()
        for bin_label in (relevant_speed_bins or [])
        if str(bin_label).strip()
    }
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in matches:
        speed = _as_float(row.get("speed_kmh"))
        amp = _as_float(row.get("amp"))
        location = str(row.get("location") or "").strip()
        if speed is None or speed <= 0 or amp is None or amp <= 0 or not location:
            continue
        speed_bin = _speed_bin_label(speed)
        if allowed_bins and speed_bin not in allowed_bins:
            continue
        grouped[speed_bin].append(
            {
                "location": location,
                "amp": amp,
                "speed_kmh": speed,
                "matched_hz": _as_float(row.get("matched_hz")),
                "rel_error": _as_float(row.get("rel_error")),
            }
        )

    if not grouped:
        return "", None

    per_bin_results: list[dict[str, object]] = []
    best: dict[str, object] | None = None
    corroboration_amp_multiplier = pow(10.0, MULTI_SENSOR_CORROBORATION_DB / 20.0)
    for bin_label, rows in grouped.items():
        if not rows:
            continue

        per_loc_scores: dict[str, list[float]] = defaultdict(list)
        per_loc_sample_counts: dict[str, int] = defaultdict(int)
        per_loc_corroborated_counts: dict[str, list[int]] = defaultdict(list)

        for row in rows:
            location = str(row.get("location") or "").strip()
            amp = _as_float(row.get("amp"))
            if not location or amp is None or amp <= 0:
                continue

            matched_hz = _as_float(row.get("matched_hz"))
            rel_error = _as_float(row.get("rel_error"))
            quality_weight = max(0.0, min(1.0, 1.0 - rel_error)) if rel_error is not None else 1.0

            corroborating_locations: set[str] = set()
            if matched_hz is not None and matched_hz > 0:
                tolerance_hz = max(0.75, matched_hz * 0.03)
                for peer in rows:
                    peer_location = str(peer.get("location") or "").strip()
                    peer_hz = _as_float(peer.get("matched_hz"))
                    if (
                        not peer_location
                        or peer_location == location
                        or peer_hz is None
                        or abs(peer_hz - matched_hz) > tolerance_hz
                    ):
                        continue
                    corroborating_locations.add(peer_location)

            corroborated_by_n_sensors = 1 + len(corroborating_locations)
            corroboration_weight = (
                corroboration_amp_multiplier if corroborated_by_n_sensors >= 2 else 1.0
            )

            per_loc_scores[location].append(amp * quality_weight * corroboration_weight)
            per_loc_sample_counts[location] += 1
            per_loc_corroborated_counts[location].append(corroborated_by_n_sensors)

        ranked = sorted(
            ((loc, mean(vals)) for loc, vals in per_loc_scores.items() if vals),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked:
            continue

        eligible_ranked = (
            [item for item in ranked if item[0] in connected_locations]
            if connected_locations is not None
            else ranked
        )
        ranked_for_winner = eligible_ranked if eligible_ranked else ranked

        # Source-aware localization: for wheel/tire diagnoses prefer wheel
        # sensors as the fault source.  Non-wheel sensors (cabin, chassis)
        # may carry transfer-path energy but should not be reported as the
        # fault origin when wheel sensors are available.
        _prefer_wheel = (suspected_source or "").strip().lower() == "wheel/tire"
        if _prefer_wheel:
            wheel_ranked = [item for item in ranked_for_winner if is_wheel_location(item[0])]
            if wheel_ranked:
                ranked_for_winner = wheel_ranked

        top_loc, top_amp = ranked_for_winner[0]
        top_count = int(per_loc_sample_counts.get(top_loc, 0))
        second_loc = ranked_for_winner[1][0] if len(ranked_for_winner) > 1 else top_loc
        second_count = (
            int(per_loc_sample_counts.get(second_loc, 0))
            if len(ranked_for_winner) > 1
            else top_count
        )
        second_amp = ranked_for_winner[1][1] if len(ranked_for_winner) > 1 else top_amp
        dominance = (top_amp / second_amp) if second_amp > 0 else 1.0
        total_samples = sum(per_loc_sample_counts.values())
        ambiguous = len(ranked_for_winner) > 1 and dominance < NEAR_TIE_DOMINANCE_THRESHOLD
        display_location = f"ambiguous location: {top_loc} / {second_loc}" if ambiguous else top_loc
        partial_coverage = bool(
            connected_locations is not None and top_loc not in connected_locations
        )
        top_corroborated_by_n_sensors = max(per_loc_corroborated_counts.get(top_loc, [1]))
        candidate = {
            "speed_range": bin_label,
            "location": display_location,
            "mean_amp": top_amp,
            "dominance_ratio": dominance,
            "location_count": len(ranked_for_winner),
            "top_location": top_loc,
            "second_location": second_loc if len(ranked_for_winner) > 1 else None,
            "top_location_samples": top_count,
            "second_location_samples": second_count,
            "corroborated_by_n_sensors": top_corroborated_by_n_sensors,
            "total_samples": total_samples,
            "ambiguous_location": ambiguous,
            "ambiguous_locations": [top_loc, second_loc] if ambiguous else [],
            "partial_coverage": partial_coverage,
            "localization_confidence": _localization_confidence(
                dominance_ratio=dominance,
                location_count=len(ranked_for_winner),
                total_samples=total_samples,
            ),
            "weak_spatial_separation": dominance
            < weak_spatial_dominance_threshold(len(ranked_for_winner)),
        }
        per_bin_results.append(candidate)
        # Prefer bins that are both strong and sufficiently sampled.
        # Pure mean-amplitude ranking lets tiny outlier bins dominate; this
        # weighted score preserves amplitude leadership while rewarding evidence
        # density via a logarithmic sample-count factor.
        candidate_score = float(candidate["mean_amp"]) * log1p(float(total_samples))
        best_score = (
            float(best["mean_amp"]) * log1p(float(best.get("total_samples") or 0))
            if best is not None
            else float("-inf")
        )
        if best is None or candidate_score > best_score:
            best = candidate

    if best is None:
        return "", None

    top_location = str(best.get("top_location") or "").strip()
    speed_weight_pairs = [
        (
            float(row.get("speed_kmh") or 0.0),
            float(row.get("amp") or 0.0),
        )
        for rows in grouped.values()
        for row in rows
        if str(row.get("location") or "").strip() == top_location
    ]
    if not speed_weight_pairs:
        speed_weight_pairs = [
            (
                float(row.get("speed_kmh") or 0.0),
                float(row.get("amp") or 0.0),
            )
            for rows in grouped.values()
            for row in rows
        ]
    weighted_speed_window = _weighted_speed_window_label(speed_weight_pairs)
    if weighted_speed_window:
        best["speed_range"] = weighted_speed_window

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
