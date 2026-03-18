"""Analysis-internal type aliases and helpers.

Boundary serialization TypedDicts (``FindingPayload``, ``AnalysisSummary``,
etc.) have been relocated to
``vibesensor.shared.boundaries.analysis_payload``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias, TypedDict

from vibesensor.shared.types.json_types import JsonObject, JsonValue
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase

Sample: TypeAlias = JsonObject
"""A single recorded sample row.  Alias for ``JsonObject``; used for
semantic clarity across analysis modules, not additional type safety."""


def i18n_ref(key: str, **params: JsonValue) -> JsonObject:
    """Build a language-neutral i18n reference dict."""
    ref: JsonObject = {"_i18n_key": key}
    if params:
        ref.update(params)
    return ref


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


PhaseLabel: TypeAlias = DrivingPhase | str
PhaseLabels: TypeAlias = Sequence[PhaseLabel]
