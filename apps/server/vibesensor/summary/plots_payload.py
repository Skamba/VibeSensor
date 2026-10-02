"""Phase, speed-breakdown, and peak-table serialization helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.summary.analysis_views import (
    PeakTableRow,
    PhaseSpeedBreakdownRow,
    SpeedBreakdownRow,
)
from vibesensor.summary.contracts import (
    PhaseSegmentSummaryResponse as PhaseSegmentSummaryPayload,
)


class SpeedBreakdownRowLike(Protocol):
    @property
    def speed_range(self) -> str: ...
    @property
    def count(self) -> int: ...
    @property
    def mean_vibration_strength_db(self) -> float | None: ...
    @property
    def max_vibration_strength_db(self) -> float | None: ...


class PhaseSpeedBreakdownRowLike(Protocol):
    @property
    def phase(self) -> str: ...
    @property
    def count(self) -> int: ...
    @property
    def mean_speed_kmh(self) -> float | None: ...
    @property
    def max_speed_kmh(self) -> float | None: ...
    @property
    def mean_vibration_strength_db(self) -> float | None: ...
    @property
    def max_vibration_strength_db(self) -> float | None: ...


class PeakTableRowLike(Protocol):
    @property
    def rank(self) -> int: ...
    @property
    def frequency_hz(self) -> float: ...
    @property
    def order_label(self) -> str: ...
    @property
    def suspected_source(self) -> str: ...
    @property
    def max_intensity_db(self) -> float | None: ...
    @property
    def median_intensity_db(self) -> float | None: ...
    @property
    def p95_intensity_db(self) -> float | None: ...
    @property
    def run_noise_baseline_db(self) -> float | None: ...
    @property
    def median_vs_run_noise_ratio(self) -> float: ...
    @property
    def p95_vs_run_noise_ratio(self) -> float: ...
    @property
    def strength_floor_db(self) -> float | None: ...
    @property
    def strength_db(self) -> float | None: ...
    @property
    def presence_ratio(self) -> float: ...
    @property
    def burstiness(self) -> float: ...
    @property
    def persistence_score(self) -> float: ...
    @property
    def peak_classification(self) -> str: ...
    @property
    def typical_speed_band(self) -> str: ...


class PhaseSegmentLike(Protocol):
    @property
    def phase(self) -> DrivingPhase: ...
    @property
    def start_idx(self) -> int: ...
    @property
    def end_idx(self) -> int: ...
    @property
    def start_t_s(self) -> float: ...
    @property
    def end_t_s(self) -> float: ...
    @property
    def speed_min_kmh(self) -> float | None: ...
    @property
    def speed_max_kmh(self) -> float | None: ...
    @property
    def sample_count(self) -> int: ...


def serialize_phase_segments(
    phase_segments: Sequence[PhaseSegmentLike],
) -> list[PhaseSegmentSummaryPayload]:
    """Serialize phase segments to JSON-safe dicts."""
    return [
        {
            "phase": seg.phase.value,
            "start_idx": seg.start_idx,
            "end_idx": seg.end_idx,
            "start_t_s": (
                None
                if isinstance(seg.start_t_s, float) and math.isnan(seg.start_t_s)
                else seg.start_t_s
            ),
            "end_t_s": (
                None if isinstance(seg.end_t_s, float) and math.isnan(seg.end_t_s) else seg.end_t_s
            ),
            "speed_min_kmh": seg.speed_min_kmh,
            "speed_max_kmh": seg.speed_max_kmh,
            "sample_count": seg.sample_count,
        }
        for seg in phase_segments
    ]


def serialize_speed_breakdown(
    rows: Sequence[SpeedBreakdownRowLike],
) -> list[SpeedBreakdownRow]:
    """Project speed-breakdown rows into their persisted summary payload shape."""
    payload_rows: list[SpeedBreakdownRow] = []
    for row in rows:
        payload: SpeedBreakdownRow = {
            "speed_range": row.speed_range,
            "count": row.count,
            "mean_vibration_strength_db": row.mean_vibration_strength_db,
            "max_vibration_strength_db": row.max_vibration_strength_db,
        }
        payload_rows.append(payload)
    return payload_rows


def serialize_phase_speed_breakdown(
    rows: Sequence[PhaseSpeedBreakdownRowLike],
) -> list[PhaseSpeedBreakdownRow]:
    """Project per-phase speed breakdown rows into persisted summary payloads."""
    payload_rows: list[PhaseSpeedBreakdownRow] = []
    for row in rows:
        payload: PhaseSpeedBreakdownRow = {
            "phase": row.phase,
            "count": row.count,
            "mean_speed_kmh": row.mean_speed_kmh,
            "max_speed_kmh": row.max_speed_kmh,
            "mean_vibration_strength_db": row.mean_vibration_strength_db,
            "max_vibration_strength_db": row.max_vibration_strength_db,
        }
        payload_rows.append(payload)
    return payload_rows


def serialize_peak_table(
    rows: Sequence[PeakTableRowLike],
) -> list[PeakTableRow]:
    """Project peak-table rows into persisted summary payload dictionaries."""
    payload_rows: list[PeakTableRow] = []
    for row in rows:
        payload: PeakTableRow = {
            "rank": row.rank,
            "frequency_hz": row.frequency_hz,
            "order_label": row.order_label,
            "max_intensity_db": row.max_intensity_db,
            "median_intensity_db": row.median_intensity_db,
            "p95_intensity_db": row.p95_intensity_db,
            "run_noise_baseline_db": row.run_noise_baseline_db,
            "median_vs_run_noise_ratio": row.median_vs_run_noise_ratio,
            "p95_vs_run_noise_ratio": row.p95_vs_run_noise_ratio,
            "strength_floor_db": row.strength_floor_db,
            "strength_db": row.strength_db,
            "presence_ratio": row.presence_ratio,
            "burstiness": row.burstiness,
            "persistence_score": row.persistence_score,
            "suspected_source": row.suspected_source,
            "peak_classification": row.peak_classification,
            "typical_speed_band": row.typical_speed_band,
        }
        payload_rows.append(payload)
    return payload_rows
