"""Focused match-rate rescue policy for tracked-order findings."""

from __future__ import annotations

from vibesensor.domain import speed_band_sort_key
from vibesensor.shared.constants import ORDER_MIN_COVERAGE_POINTS, ORDER_MIN_MATCH_POINTS


def _compute_effective_match_rate(
    match_rate: float,
    min_match_rate: float,
    possible_by_speed_bin: dict[str, int],
    matched_by_speed_bin: dict[str, int],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
) -> tuple[float, str | None, bool]:
    """Rescue a below-threshold match rate via focused speed-band or location evidence."""
    effective_match_rate = match_rate
    focused_speed_band: str | None = None
    if match_rate < min_match_rate and possible_by_speed_bin:
        highest_speed_bin = max(
            possible_by_speed_bin.keys(),
            key=lambda key: speed_band_sort_key(key),
        )
        focused_possible = int(possible_by_speed_bin[highest_speed_bin])
        focused_matched = int(matched_by_speed_bin.get(highest_speed_bin, 0))
        focused_rate = focused_matched / max(1, focused_possible)
        min_focused_possible = max(ORDER_MIN_MATCH_POINTS, ORDER_MIN_COVERAGE_POINTS // 2)
        if (
            focused_possible >= min_focused_possible
            and focused_matched >= ORDER_MIN_MATCH_POINTS
            and focused_rate >= min_match_rate
        ):
            focused_speed_band = highest_speed_bin
            effective_match_rate = focused_rate

    per_location_dominant = False
    if effective_match_rate < min_match_rate and possible_by_location:
        best_loc_rate = 0.0
        for location, loc_possible in possible_by_location.items():
            loc_matched = matched_by_location.get(location, 0)
            if loc_possible >= ORDER_MIN_COVERAGE_POINTS and loc_matched >= ORDER_MIN_MATCH_POINTS:
                loc_rate = loc_matched / max(1, loc_possible)
                best_loc_rate = max(best_loc_rate, loc_rate)
        if best_loc_rate >= min_match_rate:
            effective_match_rate = best_loc_rate
            per_location_dominant = True

    return effective_match_rate, focused_speed_band, per_location_dominant
