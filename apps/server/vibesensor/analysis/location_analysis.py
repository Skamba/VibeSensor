"""Location and speed-bin summary helpers for analysis findings."""

from __future__ import annotations

from collections.abc import Collection, Set
from dataclasses import replace
from math import pow
from typing import TYPE_CHECKING

import numpy as np

from vibesensor.analysis.constants import MULTI_SENSOR_CORROBORATION_DB
from vibesensor.analysis.location_grouping import (
    group_matches_by_speed_bin,
    location_speed_weight_pairs,
)
from vibesensor.analysis.location_scoring import (
    LocationAnalysisResult,
    score_locations_in_bin,
    select_best_location_result,
    weighted_speed_window_label,
)
from vibesensor.common.json_utils import i18n_ref

if TYPE_CHECKING:
    from vibesensor.analysis.orders.matching import MatchedWindows


def summarize_order_match_locations(
    matches: MatchedWindows,
    lang: str,
    relevant_speed_bins: Collection[str] | None = None,
    connected_locations: Set[str] | None = None,
    suspected_source: str | None = None,
    quiet_locations: Set[str] = frozenset(),
) -> tuple[object, LocationAnalysisResult | None]:
    """Return strongest location summary, optionally restricted to specific speed bins.

    A sensor is named without surrounding blanks.
    """
    del lang  # localization happens through i18n keys, not by branching here
    names = [name.strip() for name in matches.locations]
    locations = list(dict.fromkeys(names))
    code_of = np.array([locations.index(name) for name in names], dtype=np.intp)
    matches = replace(matches, location=code_of[matches.location], locations=locations)
    grouped = group_matches_by_speed_bin(matches, relevant_speed_bins=relevant_speed_bins)
    if not grouped:
        return "", None

    corroboration_amp_multiplier = pow(10.0, MULTI_SENSOR_CORROBORATION_DB / 20.0)
    per_bin_results = [
        candidate
        for bin_label, rows in grouped.items()
        if (
            candidate := score_locations_in_bin(
                bin_label,
                matches,
                rows,
                corroboration_amp_multiplier=corroboration_amp_multiplier,
                connected_locations=connected_locations,
                suspected_source=suspected_source,
                quiet_locations=quiet_locations,
            )
        )
        is not None
    ]
    best = select_best_location_result(per_bin_results)
    if best is None:
        return "", None

    speed_weight_pairs = location_speed_weight_pairs(matches, grouped, location=best.top_location)
    weighted_speed_window = weighted_speed_window_label(speed_weight_pairs)
    if weighted_speed_window:
        best = replace(best, speed_range=weighted_speed_window)

    best_out = replace(best, per_bin_results=tuple(per_bin_results))
    sentence = i18n_ref(
        "STRONGEST_AT_LOCATION_IN_SPEED_RANGE",
        location=best_out.display_location,
        speed_range=best_out.speed_range,
        dominance=f"{best_out.dominance_ratio:.2f}",
        weak_note=(
            i18n_ref("WEAK_SPATIAL_SEPARATION_NOTE") if best_out.weak_spatial_separation else ""
        ),
    )
    return sentence, best_out


__all__ = ["LocationAnalysisResult", "summarize_order_match_locations"]
