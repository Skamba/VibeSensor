"""Whole-run order-trace contracts for dense sidecars and compact summaries.

The dense trace stays keyed by ``(hypothesis_key, harmonic, window_index)`` so
later execution stages can join directly against the canonical whole-run window
grid without inventing a second order model. Compact summaries collapse those
dense points into persisted/report-facing support intervals, phase support, and
harmonic evidence rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vibesensor.shared.types.json_contract import (
    JsonContract,
    require_non_empty_text,
    require_non_negative,
    require_positive,
    require_ratio,
)

__all__ = [
    "OrderHarmonicEvidenceSummary",
    "OrderTraceFamily",
    "OrderTracePhaseSupport",
    "OrderTracePoint",
    "OrderTraceSummary",
    "OrderTraceSupportInterval",
]

type OrderTraceFamily = Literal["wheel", "driveshaft", "engine"]


@dataclass(frozen=True, slots=True)
class OrderTracePoint(JsonContract):
    """Dense whole-run order-trace point keyed to one candidate, harmonic, and window."""

    hypothesis_key: str
    suspected_source: str
    order_family: OrderTraceFamily
    harmonic: int
    order_label: str
    window_index: int
    eligible: bool
    matched: bool
    predicted_hz: float | None = None
    matched_hz: float | None = None
    relative_error: float | None = None
    peak_intensity_db: float | None = None
    vibration_strength_db: float | None = None
    ref_source: str | None = None
    strongest_location: str | None = None
    window_quality_score: float | None = None
    window_quality_state: str | None = None
    window_quality_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty_text(self, "hypothesis_key", "order_label", "suspected_source")
        require_non_negative(self, "window_index")
        require_positive(self, "harmonic")


@dataclass(frozen=True, slots=True)
class OrderTraceSupportInterval(JsonContract):
    """Compact contiguous support interval derived from dense whole-run trace points."""

    interval_index: int
    start_window_index: int
    end_window_index: int
    matched_window_count: int
    support_ratio: float
    start_t_s: float | None = None
    end_t_s: float | None = None
    phase: str | None = None
    load_state: str | None = None
    speed_band: str | None = None
    mean_relative_error: float | None = None

    def __post_init__(self) -> None:
        require_non_negative(
            self,
            "interval_index",
            "start_window_index",
            "end_window_index",
            "matched_window_count",
        )
        if self.end_window_index < self.start_window_index:
            raise ValueError("end_window_index must be >= start_window_index")
        require_ratio(self, "support_ratio")


@dataclass(frozen=True, slots=True)
class OrderTracePhaseSupport(JsonContract):
    """Compact phase-aware support row for one order-trace summary."""

    phase: str
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float

    def __post_init__(self) -> None:
        require_non_empty_text(self, "phase")
        require_non_negative(self, "eligible_window_count", "matched_window_count")
        require_ratio(self, "support_ratio")


@dataclass(frozen=True, slots=True)
class OrderHarmonicEvidenceSummary(JsonContract):
    """Compact harmonic-specific evidence row for one order-trace summary."""

    harmonic: int
    order_label: str
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float
    reference_coverage_ratio: float
    contiguous_support_ratio: float
    lock_score: float
    mean_relative_error: float | None = None
    relative_error_stddev: float | None = None
    drift_score: float = 0.0
    peak_intensity_db: float | None = None
    mean_vibration_strength_db: float | None = None

    def __post_init__(self) -> None:
        require_positive(self, "harmonic")
        require_non_empty_text(self, "order_label")
        require_non_negative(self, "eligible_window_count", "matched_window_count")
        require_ratio(
            self,
            "support_ratio",
            "reference_coverage_ratio",
            "contiguous_support_ratio",
            "lock_score",
            "drift_score",
        )


@dataclass(frozen=True, slots=True)
class OrderTraceSummary(JsonContract):
    """Compact persisted/report-facing summary derived from dense whole-run order traces."""

    hypothesis_key: str
    suspected_source: str
    order_family: OrderTraceFamily
    order_label: str
    total_window_count: int
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float
    reference_coverage_ratio: float
    longest_contiguous_support_window_count: int
    contiguous_support_ratio: float
    usable_window_count: int = 0
    limited_window_count: int = 0
    excluded_window_count: int = 0
    shock_transient_window_count: int = 0
    sensor_clipping_window_count: int = 0
    sensor_mounting_artifact_window_count: int = 0
    sensor_timing_integrity_window_count: int = 0
    speed_context_limited_window_count: int = 0
    mean_quality_score: float | None = None
    support_intervals: tuple[OrderTraceSupportInterval, ...] = ()
    phase_support: tuple[OrderTracePhaseSupport, ...] = ()
    harmonic_summaries: tuple[OrderHarmonicEvidenceSummary, ...] = ()
    stable_frequency_min_hz: float | None = None
    stable_frequency_max_hz: float | None = None
    exemplar_interval_index: int | None = None
    dominant_phase: str | None = None
    dominant_speed_band: str | None = None
    strongest_location: str | None = None
    mean_relative_error: float | None = None
    relative_error_stddev: float | None = None
    drift_score: float = 0.0
    lock_score: float = 0.0
    peak_intensity_db: float | None = None
    mean_vibration_strength_db: float | None = None
    ref_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty_text(self, "hypothesis_key", "suspected_source", "order_label")
        require_non_negative(
            self,
            "total_window_count",
            "eligible_window_count",
            "matched_window_count",
            "longest_contiguous_support_window_count",
            "usable_window_count",
            "limited_window_count",
            "excluded_window_count",
            "shock_transient_window_count",
            "sensor_clipping_window_count",
            "sensor_mounting_artifact_window_count",
            "sensor_timing_integrity_window_count",
            "speed_context_limited_window_count",
            "exemplar_interval_index",
        )
        require_ratio(
            self,
            "support_ratio",
            "reference_coverage_ratio",
            "contiguous_support_ratio",
            "drift_score",
            "lock_score",
        )
