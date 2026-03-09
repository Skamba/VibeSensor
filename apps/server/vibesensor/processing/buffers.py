"""Client buffer dataclass for signal data storage.

``ClientBuffer`` holds per-sensor circular-buffer state: raw sample
data, cached metrics/spectra, and generation counters used for
change-detection and payload caching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import numpy as np

from ..payload_types import StrengthMetricsPayload
from .models import MetricsPayload, SpectrumByAxis
from .payload import SelectedClientPayload, SpectrumSeriesPayload


def _empty_strength_metrics() -> StrengthMetricsPayload:
    return cast(StrengthMetricsPayload, {})


@dataclass(slots=True, eq=False, repr=False)
class ClientBuffer:
    """Ring-buffer accumulator for a single ESP32 client's raw accelerometer data."""

    data: np.ndarray
    capacity: int
    write_idx: int = 0
    count: int = 0
    sample_rate_hz: int = 0
    latest_metrics: MetricsPayload = field(default_factory=dict)
    latest_spectrum: SpectrumByAxis = field(default_factory=dict)
    latest_strength_metrics: StrengthMetricsPayload = field(default_factory=_empty_strength_metrics)
    last_ingest_mono_s: float = 0.0
    # Sensor-clock timestamp (µs) of the most recent ingested frame.
    # After CMD_SYNC_CLOCK this is server-relative and comparable across sensors.
    last_t0_us: int = 0
    # Number of samples ingested since last_t0_us was recorded.  Used to
    # back-compute the timestamp of the oldest sample in the analysis window.
    samples_since_t0: int = 0
    # Generation counters: ingest_generation increments on new samples,
    # compute_generation marks which ingest generation metrics reflect, and
    # spectrum_generation marks spectrum snapshot updates for payload caching.
    ingest_generation: int = 0
    compute_generation: int = -1
    compute_sample_rate_hz: int = 0
    spectrum_generation: int = 0
    cached_spectrum_payload: SpectrumSeriesPayload | None = None
    cached_spectrum_payload_generation: int = -1
    cached_selected_payload: SelectedClientPayload | None = None
    cached_selected_payload_key: tuple[int, int, int] | None = None

    def __repr__(self) -> str:
        """Compact repr that omits large numpy array data."""
        return (
            f"ClientBuffer(capacity={self.capacity}, count={self.count}, "
            f"write_idx={self.write_idx}, sr={self.sample_rate_hz}Hz, "
            f"igen={self.ingest_generation}, cgen={self.compute_generation})"
        )

    def invalidate_caches(self) -> None:
        """Reset all cached payload fields to force recomputation."""
        # Fast-path: skip redundant writes when caches are already clear.
        # During rapid ingestion invalidate_caches is called every batch but
        # compute runs less frequently, so most calls are no-ops.
        if self.cached_spectrum_payload is None and self.cached_selected_payload is None:
            return
        self.cached_spectrum_payload = None
        self.cached_spectrum_payload_generation = -1
        self.cached_selected_payload = None
        self.cached_selected_payload_key = None
