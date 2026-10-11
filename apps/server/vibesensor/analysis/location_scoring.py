"""Typed scoring helpers for location analysis."""

from __future__ import annotations

from collections.abc import Sequence, Set
from dataclasses import dataclass
from math import ceil, floor
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

from vibesensor.analysis.math_utils import _weighted_percentile
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.domain.locations import has_any_wheel_location, is_wheel_location

if TYPE_CHECKING:
    from vibesensor.analysis.orders.matching import MatchedWindows

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


def _corroborating_sensors(
    location: npt.NDArray[np.intp], matched_hz: npt.NDArray[np.float64]
) -> npt.NDArray[np.intp]:
    """How many sensors match each match's frequency: its own and every other one with a peak near.

    A peer is near within 3 % (0.75 Hz at least): another sensor's match at
    its nearest frequency either side. A match at no frequency is its own alone.
    """
    corroborated = np.ones(location.size, dtype=np.intp)
    at_hz = matched_hz > 0
    tolerance_hz = np.maximum(0.75, matched_hz * 0.03)
    for peer in np.unique(location[at_hz]).tolist():
        peer_hz = np.sort(matched_hz[at_hz & (location == peer)])
        above = np.searchsorted(peer_hz, matched_hz, side="left")
        nearest_above = peer_hz[np.minimum(above, peer_hz.size - 1)]
        nearest_below = peer_hz[np.maximum(above - 1, 0)]
        near = ((above < peer_hz.size) & (np.abs(nearest_above - matched_hz) <= tolerance_hz)) | (
            (above > 0) & (np.abs(nearest_below - matched_hz) <= tolerance_hz)
        )
        corroborated += at_hz & (location != peer) & near
    return corroborated


def score_locations_in_bin(
    bin_label: str,
    matches: MatchedWindows,
    rows: npt.NDArray[np.intp],
    *,
    corroboration_amp_multiplier: float,
    connected_locations: Set[str] | None,
    suspected_source: str | None,
    quiet_locations: Set[str] = frozenset(),
) -> LocationAnalysisResult | None:
    """Score and rank sensor locations within a single speed bin.

    *rows* are the bin's matches (positions in *matches*), whose sensors
    have no surrounding blanks (``summarize_order_match_locations``).
    *quiet_locations* are the sensors read at the order's line that do not
    hear it: they rank below every sensor that does, with no amplitude.
    """
    names = matches.locations
    location = matches.location[rows]
    amp = matches.amp[rows]
    rel_error = matches.rel_error[rows]
    corroborated = _corroborating_sensors(location, matches.matched_hz[rows])
    # A match at no amplitude counts only among the sensors matched.
    scored = np.array([bool(name) for name in names], dtype=np.bool_)[location] & ~(amp <= 0)
    quality_weight = np.where(
        rel_error >= 0, np.maximum(0.0, np.minimum(1.0, 1.0 - rel_error)), 1.0
    )
    corroboration_weight = np.where(corroborated >= 2, corroboration_amp_multiplier, 1.0)
    score = amp * quality_weight * corroboration_weight
    scored_location = location[scored]
    codes, first = np.unique(scored_location, return_index=True)
    per_loc_scores = {
        names[code]: score[scored][scored_location == code].tolist()
        for code in codes[np.argsort(first, kind="stable")].tolist()
    }
    per_loc_sample_counts = {name: len(values) for name, values in per_loc_scores.items()}
    corroborated_scored = corroborated[scored]
    per_loc_corroborated_counts = {
        names[code]: int(corroborated_scored[scored_location == code].max())
        for code in codes.tolist()
    }

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
    top_corroborated_by_n_sensors = per_loc_corroborated_counts.get(top_loc, 1)
    no_wheel_sensors = prefer_wheel and not has_any_wheel_location(
        loc for loc, amp in ranked_for_winner if amp > 0
    )
    # The sensors compared: those the order matched in this bin, quiet or not.
    # A quiet sensor with no match here is only the quieter second, not one
    # more sensor the order could be spread over.
    matched_locations = {names[code] for code in np.unique(location).tolist()}
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
