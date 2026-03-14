"""Test-plan merging and location/speed-bin summary helpers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from math import ceil, floor, log1p, pow

from ..constants import MULTI_SENSOR_CORROBORATION_DB
from ..domain import Finding, LocationHotspot, RecommendedAction, TestPlan, VibrationSource
from ..json_utils import as_float_or_none as _as_float
from ..locations import has_any_wheel_location, is_wheel_location
from ._types import (
    FindingPayload,
    JsonObject,
    LocationHotspotPayload,
    MatchedPoint,
    TestStep,
    i18n_ref,
)
from .helpers import _speed_bin_label, _weighted_percentile
from .order_analysis import _finding_actions_for_source

NEAR_TIE_DOMINANCE_THRESHOLD = 1.15

# Least-invasive-first action priority (module-level to avoid per-call rebuild).
_ACTION_PRIORITY: dict[str, int] = {
    "wheel_tire_condition": 1,
    "wheel_balance_and_runout": 2,
    "engine_mounts_and_accessories": 3,
    "driveline_mounts_and_fasteners": 3,
    "driveline_inspection": 4,
    "engine_combustion_quality": 5,
    "general_mechanical_inspection": 6,
}


def _normalized_text(value: object) -> str:
    return str(value or "").strip()


def _normalized_lower_text(value: object) -> str:
    return _normalized_text(value).lower()


def _enrich_test_step(
    step: TestStep,
    *,
    finding_confidence: float | None,
    finding_speed_band: str,
    finding_frequency: str,
) -> TestStep:
    enriched_step = dict(step)
    if finding_confidence is not None:
        enriched_step.setdefault("certainty_0_to_1", f"{finding_confidence:.4f}")
    if finding_speed_band:
        enriched_step.setdefault("speed_band", finding_speed_band)
    if finding_frequency:
        enriched_step.setdefault("frequency_hz_or_order", finding_frequency)
    return enriched_step


def _weighted_percentile_speed(
    speed_weight_pairs: list[tuple[float, float]],
    percentile_0_to_1: float,
) -> float | None:
    # Filter out non-positive speeds before delegating to the generic helper.
    valid = [(speed, weight) for speed, weight in speed_weight_pairs if speed > 0]
    return _weighted_percentile(valid, percentile_0_to_1)


def _weighted_speed_window_label(speed_weight_pairs: list[tuple[float, float]]) -> str | None:
    p10 = _weighted_percentile_speed(speed_weight_pairs, 0.10)
    p90 = _weighted_percentile_speed(speed_weight_pairs, 0.90)
    if p10 is None or p90 is None:
        return None
    low = floor(min(p10, p90))
    high = ceil(max(p10, p90))
    # Note: floor(min(...)) ≤ ceil(max(...)) is guaranteed for any finite
    # floats, so no explicit low/high swap is needed here.
    if low == high:
        return f"{low} km/h"
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
    findings: list[FindingPayload],
    lang: str,
) -> list[TestStep]:
    steps: list[TestStep] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_confidence = _as_float(finding.get("confidence"))
        finding_speed_band = _normalized_text(finding.get("strongest_speed_band"))
        finding_frequency = _normalized_text(finding.get("frequency_hz_or_order"))
        actions = finding.get("actions")
        if isinstance(actions, list) and actions:
            for step in actions:
                if not isinstance(step, dict):
                    continue
                steps.append(
                    _enrich_test_step(
                        step,
                        finding_confidence=finding_confidence,
                        finding_speed_band=finding_speed_band,
                        finding_frequency=finding_frequency,
                    ),
                )
            continue
        source = _normalized_lower_text(finding.get("suspected_source"))
        generated_steps = _finding_actions_for_source(
            source,
            strongest_location=_normalized_text(finding.get("strongest_location")),
            strongest_speed_band=finding_speed_band,
            weak_spatial_separation=bool(finding.get("weak_spatial_separation")),
        )
        for step in generated_steps:
            steps.append(
                _enrich_test_step(
                    step,
                    finding_confidence=finding_confidence,
                    finding_speed_band=finding_speed_band,
                    finding_frequency=finding_frequency,
                ),
            )

    return _prioritize_test_steps(steps)


def _domain_finding_frequency(finding: Finding) -> str:
    if finding.order.strip():
        return finding.order.strip()
    if finding.frequency_hz is None:
        return ""
    return f"{finding.frequency_hz:g} Hz"


def _merge_domain_test_plan(
    findings: Sequence[Finding],
    lang: str,
) -> list[TestStep]:
    steps: list[TestStep] = []
    for finding in findings:
        generated_steps = _finding_actions_for_source(
            finding.source_normalized,
            strongest_location=_normalized_text(finding.strongest_location),
            strongest_speed_band=_normalized_text(finding.strongest_speed_band),
            weak_spatial_separation=finding.weak_spatial_separation,
        )
        for step in generated_steps:
            steps.append(
                _enrich_test_step(
                    step,
                    finding_confidence=finding.confidence,
                    finding_speed_band=_normalized_text(finding.strongest_speed_band),
                    finding_frequency=_domain_finding_frequency(finding),
                )
            )

    return _prioritize_test_steps(steps)


def _prioritize_test_steps(steps: list[TestStep]) -> list[TestStep]:
    dedup: dict[str, TestStep] = {}
    ordered: list[TestStep] = []
    for step in steps:
        action_id = _normalized_lower_text(step.get("action_id"))
        if not action_id:
            continue
        if action_id in dedup:
            continue
        dedup[action_id] = step
        ordered.append(step)

    # Sort by priority (least-invasive first), then preserve original order as tiebreak
    ordered.sort(key=lambda s: _ACTION_PRIORITY.get(_normalized_lower_text(s.get("action_id")), 99))

    if ordered:
        return ordered[:5]
    return [
        {
            "action_id": "general_mechanical_inspection",
            "what": i18n_ref("COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS"),
            "why": i18n_ref("NO_ACTIONABLE_FINDINGS_WERE_GENERATED_FROM_CURRENT_DATA"),
            "confirm": i18n_ref(
                "CONFIRM_CONCRETE_MECHANICAL_ISSUE_IDENTIFIED",
            ),
            "falsify": i18n_ref(
                "FALSIFY_NO_ABNORMAL_PLAY_WEAR_OR_LOOSENESS",
            ),
            "eta": "20-35 min",
        },
    ]


def _step_text(value: object) -> str:
    if isinstance(value, dict):
        key = value.get("_i18n_key")
        if key is not None:
            return str(key)
    return _normalized_text(value)


def build_domain_test_plan(findings: list[FindingPayload], lang: str) -> TestPlan:
    steps = _merge_test_plan(findings, lang)
    actions: list[RecommendedAction] = []
    for priority, step in enumerate(steps, start=1):
        action_id = _normalized_lower_text(step.get("action_id"))
        if not action_id:
            continue
        actions.append(
            RecommendedAction(
                action_id=action_id,
                what=_step_text(step.get("what")),
                why=_step_text(step.get("why")),
                confirm=_step_text(step.get("confirm")),
                falsify=_step_text(step.get("falsify")),
                eta=_normalized_text(step.get("eta")) or None,
                priority=priority,
            )
        )
    return TestPlan(
        actions=tuple(actions),
        requires_additional_data=not bool(findings),
    )


def build_domain_test_plan_from_findings(findings: Sequence[Finding], lang: str) -> TestPlan:
    from ..domain.services.test_planning import plan_test_actions

    return plan_test_actions(findings, (), lang=lang)


def _score_locations_in_bin(
    bin_label: str,
    rows: list[JsonObject],
    *,
    corroboration_amp_multiplier: float,
    connected_locations: set[str] | None,
    suspected_source: str | None,
) -> LocationHotspotPayload | None:
    """Score and rank sensor locations within a single speed-bin.

    Returns a candidate dict summarising the strongest location in this bin,
    or ``None`` if no valid rows were found.
    """
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
        ((loc, sum(vals) / len(vals)) for loc, vals in per_loc_scores.items() if vals),
        key=lambda item: item[1],
        reverse=True,
    )
    if not ranked:
        return None

    eligible_ranked = (
        [item for item in ranked if item[0] in connected_locations]
        if connected_locations is not None
        else ranked
    )
    ranked_for_winner = eligible_ranked or ranked

    # Source-aware localization: for wheel/tire diagnoses prefer wheel
    # sensors as the fault source.
    _prefer_wheel = (suspected_source or "").strip().lower() == VibrationSource.WHEEL_TIRE
    if _prefer_wheel:
        wheel_ranked = [item for item in ranked_for_winner if is_wheel_location(item[0])]
        if wheel_ranked:
            ranked_for_winner = wheel_ranked

    top_loc, top_amp = ranked_for_winner[0]
    top_count = int(per_loc_sample_counts.get(top_loc, 0))
    second_loc = ranked_for_winner[1][0] if len(ranked_for_winner) > 1 else top_loc
    second_count = (
        int(per_loc_sample_counts.get(second_loc, 0)) if len(ranked_for_winner) > 1 else top_count
    )
    second_amp = ranked_for_winner[1][1] if len(ranked_for_winner) > 1 else top_amp
    dominance = (top_amp / second_amp) if second_amp > 0 else 1.0
    total_samples = sum(per_loc_sample_counts.values())
    ambiguous = len(ranked_for_winner) > 1 and dominance < NEAR_TIE_DOMINANCE_THRESHOLD
    display_location = f"ambiguous location: {top_loc} / {second_loc}" if ambiguous else top_loc
    partial_coverage = bool(connected_locations is not None and top_loc not in connected_locations)
    top_corroborated_by_n_sensors = max(per_loc_corroborated_counts.get(top_loc, [1]))
    _no_wheel_sensors = _prefer_wheel and not has_any_wheel_location(
        loc for loc, _ in ranked_for_winner
    )
    _raw_loc_conf = _localization_confidence(
        dominance_ratio=dominance,
        location_count=len(ranked_for_winner),
        total_samples=total_samples,
    )
    _loc_conf = min(_raw_loc_conf, 0.30) if _no_wheel_sensors else _raw_loc_conf
    _raw_weak_spatial = dominance < LocationHotspot.weak_spatial_threshold(
        len(ranked_for_winner)
    )
    return {
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
        "localization_confidence": _loc_conf,
        "weak_spatial_separation": _raw_weak_spatial or _no_wheel_sensors,
        "no_wheel_sensors": _no_wheel_sensors,
    }


def _location_speedbin_summary(
    matches: list[MatchedPoint],
    lang: str,
    relevant_speed_bins: list[str] | tuple[str, ...] | set[str] | None = None,
    connected_locations: set[str] | None = None,
    suspected_source: str | None = None,
) -> tuple[object, LocationHotspotPayload | None]:
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
    grouped: dict[str, list[JsonObject]] = defaultdict(list)
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
            },
        )

    if not grouped:
        return "", None

    per_bin_results: list[LocationHotspotPayload] = []
    best: LocationHotspotPayload | None = None
    corroboration_amp_multiplier = pow(10.0, MULTI_SENSOR_CORROBORATION_DB / 20.0)
    for bin_label, rows in grouped.items():
        if not rows:
            continue

        candidate = _score_locations_in_bin(
            bin_label,
            rows,
            corroboration_amp_multiplier=corroboration_amp_multiplier,
            connected_locations=connected_locations,
            suspected_source=suspected_source,
        )
        if candidate is None:
            continue
        per_bin_results.append(candidate)
        # Prefer bins that are both strong and sufficiently sampled.
        # Pure mean-amplitude ranking lets tiny outlier bins dominate; this
        # weighted score preserves amplitude leadership while rewarding evidence
        # density via a logarithmic sample-count factor.
        candidate_mean_amp = _as_float(candidate.get("mean_amp")) or 0.0
        candidate_total_samples = _as_float(candidate.get("total_samples")) or 0.0
        candidate_score = candidate_mean_amp * log1p(candidate_total_samples)
        best_score = (
            (_as_float(best.get("mean_amp")) or 0.0)
            * log1p(_as_float(best.get("total_samples")) or 0.0)
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
            _as_float(row.get("speed_kmh")) or 0.0,
            _as_float(row.get("amp")) or 0.0,
        )
        for rows in grouped.values()
        for row in rows
        if str(row.get("location") or "").strip() == top_location
    ]
    if not speed_weight_pairs:
        # Defensive fallback: top_location is always a key from per_loc_scores
        # which is built from the same grouped rows, so this branch should not
        # trigger in practice.  Guard against any future refactor that
        # introduces a mismatch between the scored and grouped data structures.
        speed_weight_pairs = [
            (
                _as_float(row.get("speed_kmh")) or 0.0,
                _as_float(row.get("amp")) or 0.0,
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
    best_out: LocationHotspotPayload = {**best}
    best_out["per_bin_results"] = [{**item} for item in per_bin_results]

    sentence = i18n_ref(
        "STRONGEST_AT_LOCATION_IN_SPEED_RANGE",
        location=str(best_out.get("location") or ""),
        speed_range=str(best_out.get("speed_range") or ""),
        dominance=f"{(_as_float(best_out.get('dominance_ratio')) or 0.0):.2f}",
        weak_note=(
            i18n_ref("WEAK_SPATIAL_SEPARATION_NOTE")
            if bool(best_out.get("weak_spatial_separation"))
            else ""
        ),
    )
    return sentence, best_out
