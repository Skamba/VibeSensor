"""Whole-run multi-sensor spatial/coherence contracts.

Dense window rows stay keyed by ``(candidate_key, window_index, sensor_id)`` so
later execution stages can join aligned per-window sensor outputs without
inventing a second spatial evidence vocabulary. Compact summaries carry only the
report/history-facing proof fields needed after persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vibesensor.common.json_contract import (
    JsonContract,
    require_non_empty_text,
    require_non_negative,
    require_ratio,
)

__all__ = [
    "LocationProofBasis",
    "SpatialEvidenceSummary",
    "SpatialEvidenceWindow",
    "SpatialLocationSummary",
]

type LocationProofBasis = Literal[
    "whole_run_summary",
    "supporting_windows_raw_backed",
    "supporting_windows_summary_only",
]


@dataclass(frozen=True, slots=True)
class SpatialEvidenceWindow(JsonContract):
    """Dense spatial/coherence evidence row for one candidate-window-sensor join."""

    candidate_key: str
    suspected_source: str
    window_index: int
    sensor_id: str
    location: str
    supporting: bool
    coherent: bool
    peak_intensity_db: float | None = None
    vibration_strength_db: float | None = None
    matched_frequency_hz: float | None = None
    coherence_score: float | None = None

    def __post_init__(self) -> None:
        require_non_empty_text(self, "candidate_key", "suspected_source", "sensor_id", "location")
        require_non_negative(self, "window_index")


@dataclass(frozen=True, slots=True)
class SpatialLocationSummary(JsonContract):
    """Compact per-location support row for persisted spatial evidence."""

    location: str
    sensor_ids: tuple[str, ...]
    supporting_window_count: int
    support_ratio: float
    coherent_window_count: int = 0
    coherence_ratio: float | None = None
    peak_intensity_db: float | None = None
    mean_vibration_strength_db: float | None = None

    def __post_init__(self) -> None:
        require_non_empty_text(self, "location")
        require_non_negative(self, "supporting_window_count", "coherent_window_count")
        require_ratio(self, "support_ratio", "coherence_ratio")


@dataclass(frozen=True, slots=True)
class SpatialEvidenceSummary(JsonContract):
    """Compact persisted/report-facing whole-run spatial evidence summary."""

    candidate_key: str
    suspected_source: str
    proof_basis: LocationProofBasis
    total_window_count: int
    supporting_window_count: int
    supporting_sensor_count: int
    coherent_window_count: int = 0
    coherence_ratio: float | None = None
    dominant_location: str | None = None
    runner_up_location: str | None = None
    location_separation_db: float | None = None
    dominance_ratio: float | None = None
    ambiguous_location: bool = False
    weak_spatial_separation: bool = False
    location_summaries: tuple[SpatialLocationSummary, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty_text(self, "candidate_key", "suspected_source")
        require_non_negative(
            self,
            "total_window_count",
            "supporting_window_count",
            "supporting_sensor_count",
            "coherent_window_count",
        )
        require_ratio(self, "coherence_ratio")
