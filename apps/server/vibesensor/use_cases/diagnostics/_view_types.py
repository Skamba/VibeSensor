"""Diagnostics output/view dataclasses used by summary tables and reports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpeedBreakdownRowData:
    speed_range: str
    count: int
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


@dataclass(frozen=True, slots=True)
class PhaseSpeedBreakdownRowData:
    phase: str
    count: int
    mean_speed_kmh: float | None
    max_speed_kmh: float | None
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


@dataclass(frozen=True, slots=True)
class PeakTableRowData:
    rank: int
    frequency_hz: float
    order_label: str
    suspected_source: str
    max_intensity_db: float | None
    median_intensity_db: float | None
    p95_intensity_db: float | None
    run_noise_baseline_db: float | None
    median_vs_run_noise_ratio: float
    p95_vs_run_noise_ratio: float
    strength_floor_db: float | None
    strength_db: float | None
    presence_ratio: float
    burstiness: float
    persistence_score: float
    peak_classification: str
    typical_speed_band: str

    @property
    def peaks(self) -> PeakClassificationRowView:
        """Return the peak-classification view expected by serializers and reports."""
        return PeakClassificationRowView(classification=self.peak_classification)


@dataclass(frozen=True, slots=True)
class PeakClassificationRowView:
    """Minimal nested view of peak classification for report payload builders."""

    classification: str
