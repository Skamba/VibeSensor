"""Typed scoring helpers for location analysis."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Sequence, Set
from dataclasses import dataclass
from math import ceil, floor

from vibesensor.analysis.math_utils import _weighted_percentile
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.domain.locations import has_any_wheel_location, is_wheel_location
from vibesensor.domain.order_match import OrderMatchObservation

NEAR_TIE_DOMINANCE_THRESHOLD = 1.15
QUIET_SECOND_DOMINANCE = 10.0


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
    weak_spatial_threshold: float
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


def _peer_hz_by_location(matches: Sequence[OrderMatchObservation]) -> dict[str, list[float]]:
    """Each sensor's matched frequencies, sorted: the peers that can corroborate a match."""
    by_location: dict[str, list[float]] = defaultdict(list)
    for peer in matches:
        peer_location = peer.location.strip()
        if peer_location and peer.matched_hz > 0:
            by_location[peer_location].append(peer.matched_hz)
    for peer_hz in by_location.values():
        peer_hz.sort()
    return by_location


def _has_peer_within(sorted_hz: Sequence[float], hz: float, tolerance_hz: float) -> bool:
    """Whether any of *sorted_hz* lies within *tolerance_hz* of *hz*: the nearest either side."""
    above = bisect_left(sorted_hz, hz)
    return (above < len(sorted_hz) and abs(sorted_hz[above] - hz) <= tolerance_hz) or (
        above > 0 and abs(sorted_hz[above - 1] - hz) <= tolerance_hz
    )


def score_locations_in_bin(
    bin_label: str,
    matches: Sequence[OrderMatchObservation],
    *,
    corroboration_amp_multiplier: float,
    connected_locations: Set[str] | None,
    suspected_source: str | None,
    quiet_locations: Set[str] = frozenset(),
) -> LocationAnalysisResult | None:
    """Score and rank sensor locations within a single speed bin.

    *quiet_locations* are the sensors read at the order's line that do not
    hear it: they rank below every sensor that does, with no amplitude.
    """
    per_loc_scores: dict[str, list[float]] = defaultdict(list)
    per_loc_sample_counts: dict[str, int] = defaultdict(int)
    per_loc_corroborated_counts: dict[str, list[int]] = defaultdict(list)
    peer_hz_by_location = _peer_hz_by_location(matches)

    for match in matches:
        location = match.location.strip()
        amp = match.amp
        if not location or amp <= 0:
            continue

        matched_hz = match.matched_hz if match.matched_hz > 0 else None
        rel_error = match.rel_error if match.rel_error >= 0 else None
        quality_weight = max(0.0, min(1.0, 1.0 - rel_error)) if rel_error is not None else 1.0

        corroborated_by_n_sensors = 1
        if matched_hz is not None:
            tolerance_hz = max(0.75, matched_hz * 0.03)
            corroborated_by_n_sensors += sum(
                1
                for peer_location, peer_hz in peer_hz_by_location.items()
                if peer_location != location and _has_peer_within(peer_hz, matched_hz, tolerance_hz)
            )
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
    ranked += [(loc, 0.0) for loc in sorted(quiet_locations - per_loc_scores.keys())]

    eligible_ranked = (
        [item for item in ranked if item[0] in connected_locations]
        if connected_locations is not None
        else ranked
    )
    ranked_for_winner = eligible_ranked or ranked

    prefer_wheel = (suspected_source or "").strip().lower() == VibrationSource.WHEEL_TIRE
    if prefer_wheel:
        wheel_ranked = [item for item in ranked_for_winner if is_wheel_location(item[0])]
        # Only where a wheel sensor places the order: quiet wheels alone do not.
        if any(amp > 0 for _location, amp in wheel_ranked):
            # A lone wheel sensor is still compared with the strongest other sensor.
            others = [item for item in ranked_for_winner if not is_wheel_location(item[0])]
            ranked_for_winner = wheel_ranked + (others[:1] if len(wheel_ranked) == 1 else [])

    top_loc, top_amp = ranked_for_winner[0]
    top_count = int(per_loc_sample_counts.get(top_loc, 0))
    second_loc = ranked_for_winner[1][0] if len(ranked_for_winner) > 1 else top_loc
    second_count = (
        int(per_loc_sample_counts.get(second_loc, 0)) if len(ranked_for_winner) > 1 else top_count
    )
    second_amp = ranked_for_winner[1][1] if len(ranked_for_winner) > 1 else top_amp
    dominance = (
        (top_amp / second_amp)
        if second_amp > 0
        else QUIET_SECOND_DOMINANCE
        if top_amp > 0 and len(ranked_for_winner) > 1
        else 1.0
    )
    total_samples = sum(per_loc_sample_counts.values())
    ambiguous = len(ranked_for_winner) > 1 and dominance < NEAR_TIE_DOMINANCE_THRESHOLD
    partial_coverage = bool(connected_locations is not None and top_loc not in connected_locations)
    top_corroborated_by_n_sensors = max(per_loc_corroborated_counts.get(top_loc, [1]))
    no_wheel_sensors = prefer_wheel and not has_any_wheel_location(
        loc for loc, amp in ranked_for_winner if amp > 0
    )
    # The sensors compared: those the order matched in this bin, quiet or not.
    # A quiet sensor with no match here is only the quieter second, not one
    # more sensor the order could be spread over.
    matched_locations = {match.location.strip() for match in matches}
    location_count = max(
        sum(1 for loc, _amp in ranked_for_winner if loc in matched_locations),
        min(2, len(ranked_for_winner)),
    )
    raw_loc_conf = LocationHotspot.compute_confidence(
        dominance_ratio=dominance,
        location_count=location_count,
        total_samples=total_samples,
    )
    loc_conf = min(raw_loc_conf, 0.30) if no_wheel_sensors else raw_loc_conf
    weak_spatial_threshold = LocationHotspot.weak_spatial_threshold(location_count)
    raw_weak_spatial = dominance < weak_spatial_threshold
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
        weak_spatial_threshold=weak_spatial_threshold,
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
    """Pick the speed bin holding the most order amplitude (mean amplitude x matches).

    A short stretch at speeds the rest of the drive did not reach must not
    name the location over the bins that hold most of the evidence.
    """
    return max(
        candidates,
        key=lambda candidate: candidate.mean_amp * candidate.total_samples,
        default=None,
    )


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
