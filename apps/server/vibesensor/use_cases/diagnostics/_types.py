"""Diagnostics-internal type aliases."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.sensor_frame import SensorFrame

type Sample = SensorFrame


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


type PhaseLabel = DrivingPhase | str
type PhaseLabels = Sequence[PhaseLabel]
