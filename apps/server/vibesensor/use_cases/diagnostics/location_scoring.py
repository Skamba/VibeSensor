"""Typed scoring helpers for location analysis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence, Set
from dataclasses import dataclass
from math import ceil, floor, log1p

from vibesensor.domain import LocationHotspot, OrderMatchObservation, VibrationSource
from vibesensor.shared.locations import has_any_wheel_location, is_wheel_location
from vibesensor.use_cases.diagnostics.math_utils import _weighted_percentile

NEAR_TIE_DOMINANCE_THRESHOLD = 1.15


@dataclass(frozen=True, slots=True)
class LocationAnalysisResult:
    """Typed result from location scoring within a speed bin."""

    hotspot: LocationHotspot
    mean_amp: float
    total_samples: int
    ambiguous_location: bool
    no_wheel_sensors: bool
    speed_range: str
    dominance_ratio: float
    localization_confidence: float
    weak_spatial_separation: bool
    top_location: str
    second_location: str | None
    partial_coverage: bool
    corroborated_by_n_sensors: int
    top_location_samples: int = 0
    second_location_samples: int = 0
    per_bin_results: tuple[LocationAnalysisResult, ...] = ()

    @property
    def display_location(self) -> str:
        """Human-readable location string matching legacy ``location`` key."""
        if self.ambiguous_location and self.second_location:
            return f"ambiguous location: {self.top_location} / {self.second_location}"
        return self.top_location


def score_locations_in_bin(
    bin_label: str,
    matches: Sequence[OrderMatchObservation],
    *,
    corroboration_amp_multiplier: float,
    connected_locations: Set[str] | None,
    suspected_source: str | None,
) -> LocationAnalysisResult | None:
    """Score and rank sensor locations within a single speed bin."""
    per_loc_scores: dict[str, list[float]] = defaultdict(list)
    per_loc_sample_counts: dict[str, int] = defaultdict(int)
    per_loc_corroborated_counts: dict[str, list[int]] = defaultdict(list)

    for match in matches:
        location = match.location.strip()
        amp = match.amp
        if not location or amp <= 0:
            continue

        matched_hz = match.matched_hz if match.matched_hz > 0 else None
        rel_error = match.rel_error if match.rel_error >= 0 else None
        quality_weight = max(0.0, min(1.0, 1.0 - rel_error)) if rel_error is not None else 1.0

        corroborating_locations: set[str] = set()
        if matched_hz is not None:
            tolerance_hz = max(0.75, matched_hz * 0.03)
            for peer in matches:
                peer_location = peer.location.strip()
                peer_hz = peer.matched_hz if peer.matched_hz > 0 else None
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

    prefer_wheel = (suspected_source or "").strip().lower() == VibrationSource.WHEEL_TIRE
    if prefer_wheel:
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
    partial_coverage = bool(connected_locations is not None and top_loc not in connected_locations)
    top_corroborated_by_n_sensors = max(per_loc_corroborated_counts.get(top_loc, [1]))
    no_wheel_sensors = prefer_wheel and not has_any_wheel_location(
        loc for loc, _ in ranked_for_winner
    )
    raw_loc_conf = LocationHotspot.compute_confidence(
        dominance_ratio=dominance,
        location_count=len(ranked_for_winner),
        total_samples=total_samples,
    )
    loc_conf = min(raw_loc_conf, 0.30) if no_wheel_sensors else raw_loc_conf
    raw_weak_spatial = dominance < LocationHotspot.weak_spatial_threshold(len(ranked_for_winner))
    domain_hotspot = LocationHotspot.from_analysis_inputs(
        strongest_location=top_loc,
        dominance_ratio=dominance,
        localization_confidence=loc_conf,
        weak_spatial_separation=raw_weak_spatial or no_wheel_sensors,
        ambiguous=ambiguous,
        alternative_locations=[top_loc, second_loc] if ambiguous else [],
    )
    return LocationAnalysisResult(
        hotspot=domain_hotspot,
        mean_amp=top_amp,
        total_samples=total_samples,
        ambiguous_location=ambiguous,
        no_wheel_sensors=no_wheel_sensors,
        speed_range=bin_label,
        dominance_ratio=dominance,
        localization_confidence=loc_conf,
        weak_spatial_separation=raw_weak_spatial or no_wheel_sensors,
        top_location=top_loc,
        second_location=second_loc if len(ranked_for_winner) > 1 else None,
        partial_coverage=partial_coverage,
        corroborated_by_n_sensors=top_corroborated_by_n_sensors,
        top_location_samples=top_count,
        second_location_samples=second_count,
    )


def select_best_location_result(
    candidates: Sequence[LocationAnalysisResult],
) -> LocationAnalysisResult | None:
    """Pick the strongest per-bin location result."""
    best: LocationAnalysisResult | None = None
    for candidate in candidates:
        candidate_score = candidate.mean_amp * log1p(candidate.total_samples)
        best_score = (
            best.mean_amp * log1p(best.total_samples) if best is not None else float("-inf")
        )
        if best is None or candidate_score > best_score:
            best = candidate
    return best


def weighted_speed_window_label(speed_weight_pairs: Sequence[tuple[float, float]]) -> str | None:
    """Return a human-readable weighted speed window for one location winner."""
    valid = [(speed, weight) for speed, weight in speed_weight_pairs if speed > 0]
    p10 = _weighted_percentile(valid, 0.10)
    p90 = _weighted_percentile(valid, 0.90)
    if p10 is None or p90 is None:
        return None
    low = floor(min(p10, p90))
    high = ceil(max(p10, p90))
    if low == high:
        return f"{low} km/h"
    return f"{low}-{high} km/h"
