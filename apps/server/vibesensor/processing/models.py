from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias, TypedDict

import numpy as np
import numpy.typing as npt

from vibesensor.core.vibration_strength import VibrationStrengthMetrics

from ..payload_types import AxisPeak, MetricsPayload

FloatArray: TypeAlias = npt.NDArray[np.float32]
IntIndexArray: TypeAlias = npt.NDArray[np.intp]


class SpectrumAxisData(TypedDict):
    freq: FloatArray
    amp: FloatArray


SpectrumByAxis: TypeAlias = dict[str, SpectrumAxisData]


class FftSpectrumResult(TypedDict):
    freq_slice: FloatArray
    spectrum_by_axis: SpectrumByAxis
    axis_amp_slices: list[FloatArray]
    axis_amps: dict[str, FloatArray]
    combined_amp: FloatArray
    strength_metrics: VibrationStrengthMetrics
    axis_peaks: dict[str, list[AxisPeak]]


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
    total_compute_calls: int = 0
    last_compute_duration_s: float = 0.0
    last_compute_all_duration_s: float = 0.0
    last_ingest_duration_s: float = 0.0


@dataclass(frozen=True, slots=True)
class CachedMetricsHit:
    """Fast-path result when the latest metrics already match current input."""

    metrics: MetricsPayload


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """Immutable compute input copied from shared buffer state."""

    client_id: str
    sample_rate_hz: int
    ingest_generation: int
    time_window: FloatArray
    fft_block: FloatArray | None


@dataclass(frozen=True, slots=True)
class MetricsComputationResult:
    """Computed metrics/spectrum ready to commit back into shared state."""

    client_id: str
    sample_rate_hz: int
    ingest_generation: int
    metrics: MetricsPayload
    spectrum_by_axis: SpectrumByAxis
    strength_metrics: VibrationStrengthMetrics
    has_fft_data: bool
    duration_s: float


@dataclass(frozen=True, slots=True)
class DebugSpectrumRequest:
    """Debug FFT request copied from shared state under the store lock."""

    client_id: str
    sample_rate_hz: int
    count: int
    fft_block: FloatArray | None
