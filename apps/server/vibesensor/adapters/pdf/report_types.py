"""Adapter-local typed shapes used by PDF/report rendering helpers."""

from __future__ import annotations

from typing import TypedDict

__all__ = ["PeakTableRow"]


class PeakTableRow(TypedDict):
    """Shape of a single row in the ranked peak table."""

    rank: int
    frequency_hz: float
    order_label: str
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
    suspected_source: str
    peak_classification: str
    typical_speed_band: str
