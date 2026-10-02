from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.fft_analysis import FloatArray, SpectrumAxisData, SpectrumByAxis
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange
from vibesensor.shared.types.payload_types import ClientMetrics
from vibesensor.vibration_strength import VibrationStrengthMetrics

__all__ = [
    "ClientMetrics",
    "FloatArray",
    "MetricsComputationResult",
    "MetricsSnapshot",
    "ProcessorConfig",
    "ProcessorStats",
    "SpectrumAxisData",
    "SpectrumByAxis",
]


@dataclass(frozen=True, slots=True)
class ProcessorConfig:
    """Immutable live-processing configuration."""

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
    """Mutable observability counters owned by the signal processor."""

    total_ingested_samples: int = 0
    buffer_overflow_drops: int = 0
    total_compute_calls: int = 0
    last_compute_duration_s: float = 0.0
    last_compute_all_duration_s: float = 0.0
    last_ingest_duration_s: float = 0.0


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
