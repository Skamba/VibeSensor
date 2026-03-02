"""Client buffer dataclass for signal data storage.

``ClientBuffer`` holds per-sensor circular-buffer state: raw sample
data, cached metrics/spectra, and generation counters used for
change-detection and payload caching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(slots=True)
class ClientBuffer:
    data: np.ndarray
    capacity: int
    write_idx: int = 0
    count: int = 0
    sample_rate_hz: int = 0
    latest_metrics: dict[str, Any] = field(default_factory=dict)
    latest_spectrum: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    latest_strength_metrics: dict[str, Any] = field(default_factory=dict)
    last_ingest_mono_s: float = 0.0
    first_ingest_mono_s: float = 0.0
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
    cached_spectrum_payload: dict[str, Any] | None = None
    cached_spectrum_payload_generation: int = -1
    cached_selected_payload: dict[str, Any] | None = None
    cached_selected_payload_key: tuple[int, int, int] | None = None

    def invalidate_caches(self) -> None:
        """Reset all cached payload fields to force recomputation."""
        self.cached_spectrum_payload = None
        self.cached_spectrum_payload_generation = -1
        self.cached_selected_payload = None
        self.cached_selected_payload_key = None
