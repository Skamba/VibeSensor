"""Typed intermediate models for order-finding assembly."""

from __future__ import annotations

from dataclasses import dataclass

from ._types import MatchedPoint


@dataclass(frozen=True)
class OrderMatchAccumulator:
    """Accumulated statistics from matching one hypothesis across samples."""

    possible: int
    matched: int
    matched_amp: list[float]
    matched_floor: list[float]
    rel_errors: list[float]
    predicted_vals: list[float]
    measured_vals: list[float]
    matched_points: list[MatchedPoint]
    ref_sources: set[str]
    possible_by_speed_bin: dict[str, int]
    matched_by_speed_bin: dict[str, int]
    possible_by_phase: dict[str, int]
    matched_by_phase: dict[str, int]
    possible_by_location: dict[str, int]
    matched_by_location: dict[str, int]
    has_phases: bool
    compliance: float


@dataclass(frozen=True)
class OrderFindingBuildContext:
    """Stable context for assembling a matched order hypothesis into a finding."""

    effective_match_rate: float
    focused_speed_band: str | None
    per_location_dominant: bool
    match_rate: float
    min_match_rate: float
    constant_speed: bool
    steady_speed: bool
    connected_locations: set[str]
    lang: str
