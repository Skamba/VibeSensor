from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

import numpy as np
import numpy.typing as npt

from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange
from vibesensor.shared.types.payload_types import AxisPeak, ClientMetrics
from vibesensor.vibration_strength import VibrationStrengthMetrics

type FloatArray = npt.NDArray[np.float32]
type IntIndexArray = npt.NDArray[np.intp]
type BoolArray = npt.NDArray[np.bool_]

Axis = Literal["x", "y", "z"]


class SpectrumAxisData(TypedDict):
    freq: FloatArray
    amp: FloatArray


type SpectrumByAxis = dict[str, SpectrumAxisData]


class FftSpectrumResult(TypedDict):
    freq_slice: FloatArray
    spectrum_by_axis: SpectrumByAxis
    combined_amp: FloatArray
    strength_metrics: VibrationStrengthMetrics
    axis_peaks: dict[Axis, list[AxisPeak]]


@dataclass(frozen=True, slots=True)
class ProcessorConfig:
    """Immutable processing configuration shared across subsystems."""

    sample_rate_hz: int
    waveform_seconds: int
    waveform_display_hz: int
    fft_n: int
    spectrum_min_hz: float
    spectrum_max_hz: float
    accel_scale_g_per_lsb: float | None

    @property
    def max_samples(self) -> int:
        return self.sample_rate_hz * self.waveform_seconds


@dataclass(slots=True)
class ProcessorStats:
    """Mutable observability counters owned by the buffer store."""

    total_ingested_samples: int = 0
    buffer_overflow_drops: int = 0
    total_compute_calls: int = 0
    last_compute_duration_s: float = 0.0
    last_compute_all_duration_s: float = 0.0
    last_ingest_duration_s: float = 0.0


@dataclass(frozen=True, slots=True)
class CachedMetricsHit:
    """Fast-path result when the latest metrics already match current input."""

    metrics: ClientMetrics


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """Immutable compute input copied from shared buffer state."""

    client_id: str
    sample_rate_hz: int
    ingest_generation: int
    time_window: FloatArray
    fft_block: FloatArray | None
    analysis_time_range: AnalysisTimeRange | None = None
    buffer_epoch: int = 0
    reset_generation: int = 0


@dataclass(frozen=True, slots=True)
class MetricsComputationResult:
    """Computed metrics/spectrum ready to commit back into shared state."""

    client_id: str
    sample_rate_hz: int
    ingest_generation: int
    metrics: ClientMetrics
    spectrum_by_axis: SpectrumByAxis
    strength_metrics: VibrationStrengthMetrics
    has_fft_data: bool
    duration_s: float
    analysis_time_range: AnalysisTimeRange | None = None
    buffer_epoch: int = 0
    reset_generation: int = 0
