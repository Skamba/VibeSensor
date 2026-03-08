"""Shared lightweight typing aliases for the analysis package."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeAlias, TypedDict

from .phase_segmentation import DrivingPhase

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

Sample: TypeAlias = JsonObject
MetadataDict: TypeAlias = JsonObject
SummaryData: TypeAlias = JsonObject
IntensityRow: TypeAlias = JsonObject
Finding: TypeAlias = JsonObject
I18nRef: TypeAlias = JsonObject
TestStep: TypeAlias = JsonObject


class SpeedStats(TypedDict):
    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    range_kmh: float | None
    steady_speed: bool


class PhaseSpeedStats(SpeedStats):
    sample_count: int


class PhaseSummary(TypedDict):
    phase_counts: dict[str, int]
    phase_pcts: dict[str, float]
    total_samples: int
    segment_count: int
    has_cruise: bool
    has_acceleration: bool
    cruise_pct: float
    idle_pct: float
    speed_unknown_pct: float


class SpeedBreakdownRow(TypedDict):
    speed_range: str
    count: int
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


class PhaseSpeedBreakdownRow(TypedDict):
    phase: str
    count: int
    mean_speed_kmh: float | None
    max_speed_kmh: float | None
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


class PhaseTimelineEntry(TypedDict):
    phase: str
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    has_fault_evidence: bool


class PhaseSegmentSummary(TypedDict):
    phase: str
    start_idx: int
    end_idx: int
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    sample_count: int


class OriginSummary(TypedDict, total=False):
    location: str
    alternative_locations: list[str]
    source: str
    dominance_ratio: float | None
    weak_spatial_separation: bool
    speed_band: str | None
    dominant_phase: str | None
    explanation: JsonValue


class AccelStatistics(TypedDict):
    accel_x_vals: list[float]
    accel_y_vals: list[float]
    accel_z_vals: list[float]
    accel_mag_vals: list[float]
    amp_metric_values: list[float]
    sat_count: int
    sensor_limit: float | None
    x_mean: float | None
    x_var: float | None
    y_mean: float | None
    y_var: float | None
    z_mean: float | None
    z_var: float | None


class RunSuitabilityCheck(TypedDict):
    check: str
    check_key: str
    state: str
    explanation: JsonValue


PhaseLabel: TypeAlias = DrivingPhase | str
PhaseLabels: TypeAlias = Sequence[PhaseLabel]
Translator: TypeAlias = Callable[[str], str]
