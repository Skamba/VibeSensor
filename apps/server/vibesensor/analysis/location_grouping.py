"""Typed grouping helpers for location analysis."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from vibesensor.analysis.orders.matching import MatchedWindows


def group_matches_by_speed_bin(
    matches: MatchedWindows,
    *,
    relevant_speed_bins: Collection[str] | None = None,
) -> dict[str, npt.NDArray[np.intp]]:
    """Each speed bin's matches used for localization (positions in *matches*, in order).

    The bins come in the order their first match does. A match at no
    amplitude (a quiet sensor's, ``scoring._at_tracked_levels``) is kept: it
    counts its sensor among those the order matched in its bin. A match
    while not moving, at a negative amplitude or with no sensor is not.
    """
    allowed_bins = {
        str(bin_label).strip()
        for bin_label in (relevant_speed_bins or [])
        if str(bin_label).strip()
    }
    usable_bin = np.array(
        [
            label is not None and (not allowed_bins or label in allowed_bins)
            for label in matches.speed_bins
        ],
        dtype=np.bool_,
    )
    located = np.array([bool(name.strip()) for name in matches.locations], dtype=np.bool_)
    kept = np.flatnonzero(
        usable_bin[matches.speed_bin] & located[matches.location] & ~(matches.amp < 0)
    )
    speed_bin = matches.speed_bin[kept]
    codes, first = np.unique(speed_bin, return_index=True)
    return {
        str(matches.speed_bins[code]): kept[speed_bin == code]
        for code in codes[np.argsort(first, kind="stable")].tolist()
    }


def location_speed_weight_pairs(
    matches: MatchedWindows,
    grouped: Mapping[str, npt.NDArray[np.intp]],
    *,
    location: str,
) -> list[tuple[float, float]]:
    """Collect (speed, amplitude) pairs of the grouped matches for one winning location.

    Every location's where the winner has none at an amplitude.
    """
    rows = np.concatenate(list(grouped.values()))
    loud = matches.amp[rows] > 0
    at_location = np.array(
        [name.strip() == location.strip() for name in matches.locations], dtype=np.bool_
    )[matches.location[rows]]
    pairs = rows[loud & at_location]
    if not pairs.size:
        pairs = rows[loud]
    return list(zip(matches.speed_kmh[pairs].tolist(), matches.amp[pairs].tolist(), strict=True))
