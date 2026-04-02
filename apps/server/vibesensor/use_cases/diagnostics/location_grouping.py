"""Typed grouping helpers for location analysis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence

from vibesensor.domain import OrderMatchObservation, speed_bin_label


def group_matches_by_speed_bin(
    matches: Sequence[OrderMatchObservation],
    *,
    relevant_speed_bins: Collection[str] | None = None,
) -> dict[str, list[OrderMatchObservation]]:
    """Group typed order matches into speed bins used for localization."""
    allowed_bins = {
        str(bin_label).strip()
        for bin_label in (relevant_speed_bins or [])
        if str(bin_label).strip()
    }
    grouped: dict[str, list[OrderMatchObservation]] = defaultdict(list)
    for match in matches:
        speed = match.speed_kmh
        location = match.location.strip()
        if speed is None or speed <= 0 or match.amp <= 0 or not location:
            continue
        speed_bin = speed_bin_label(speed)
        if allowed_bins and speed_bin not in allowed_bins:
            continue
        grouped[speed_bin].append(match)
    return grouped


def location_speed_weight_pairs(
    grouped: Mapping[str, Sequence[OrderMatchObservation]],
    *,
    location: str,
) -> list[tuple[float, float]]:
    """Collect (speed, amplitude) pairs for one winning location."""
    location = location.strip()
    pairs = [
        (match.speed_kmh or 0.0, match.amp)
        for rows in grouped.values()
        for match in rows
        if match.location.strip() == location and match.speed_kmh is not None and match.amp > 0
    ]
    if pairs:
        return pairs
    return [
        (match.speed_kmh or 0.0, match.amp)
        for rows in grouped.values()
        for match in rows
        if match.speed_kmh is not None and match.amp > 0
    ]
