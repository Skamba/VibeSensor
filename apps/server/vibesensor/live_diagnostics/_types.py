"""Shared constants, dataclasses, and pure helpers for live diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from vibesensor_core.vibration_strength import vibration_strength_db_scalar

from ..constants import SILENCE_DB

SOURCE_KEYS = ("engine", "driveshaft", "wheel", "other")
SEVERITY_KEYS = ("l5", "l4", "l3", "l2", "l1")

_MULTI_SYNC_WINDOW_MS = 800
"""Sensor sync window for multi-client alignment (milliseconds)."""

_MULTI_FREQ_BIN_HZ = 1.5
"""Frequency bin width for multi-sensor correlation (Hz)."""

_HEARTBEAT_EMIT_INTERVAL_MS = 3000
"""Minimum interval between WebSocket heartbeat emissions (milliseconds)."""

_PHASE_HISTORY_MAX = 5
_MATRIX_WINDOW_MS = 5 * 60 * 1000


def _combine_amplitude_strength_db(values_db: list[float]) -> float:
    if not values_db:
        return SILENCE_DB
    linear: list[float] = []
    for value in values_db:
        v = float(value)
        if not math.isfinite(v):
            continue  # skip NaN/Inf — they would poison the mean
        linear.append(10.0 ** (max(-60.0, min(200.0, v)) / 20.0))
    if not linear:
        return SILENCE_DB
    mean_linear = sum(linear) / len(linear)
    if mean_linear <= 0.0:
        return SILENCE_DB
    return vibration_strength_db_scalar(
        peak_band_rms_amp_g=mean_linear,
        floor_amp_g=1.0,
        epsilon_g=1e-9,
    )


@dataclass(slots=True)
class _RecentEvent:
    ts_ms: int
    sensor_id: str
    sensor_label: str
    sensor_location: str
    peak_hz: float
    peak_amp: float
    vibration_strength_db: float
    class_key: str


@dataclass(slots=True)
class _TrackerLevelState:
    last_strength_db: float = SILENCE_DB
    last_band_rms_g: float = 0.0
    current_bucket_key: str | None = None
    last_update_ms: int = 0
    last_peak_hz: float = 0.0
    last_class_key: str = "other"
    last_sensor_label: str = ""
    last_sensor_location: str = ""
    last_emitted_ms: int = 0
    severity_state: dict[str, Any] | None = None
    _silence_ticks: int = 0


@dataclass(slots=True)
class _MatrixCountEvent:
    ts_ms: int
    source_key: str
    severity_key: str
    contributor_label: str


@dataclass(slots=True)
class _MatrixSecondsEvent:
    ts_ms: int
    source_key: str
    severity_key: str
    dt_seconds: float
