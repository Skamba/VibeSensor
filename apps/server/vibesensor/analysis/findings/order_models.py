"""Typed intermediate models for order-finding assembly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .._types import MatchedPoint, MetadataDict, Sample


class OrderHypothesisLike(Protocol):
    @property
    def key(self) -> str: ...

    @property
    def suspected_source(self) -> str: ...

    @property
    def order_label_base(self) -> str: ...

    @property
    def order(self) -> int: ...

    @property
    def path_compliance(self) -> float: ...

    def predicted_hz(
        self,
        sample: Sample,
        metadata: MetadataDict,
        tire_circumference_m: float | None,
    ) -> tuple[float | None, str]: ...


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
